"""Website asset management (spec §26).

Upload / preview / replace / delete / resize / compress for images, video,
documents, fonts and icons. Assets live inside the project's repo under assets/ so
they publish and are served with the site. Image resize/compress are REAL (Pillow).

SECURITY (spec §31 — file-upload safety): every upload is size-checked, extension-
whitelisted per kind, and its filename sanitized (no path traversal, no surprising
extensions). Images are re-opened with Pillow to confirm they are actually images.
Nothing here executes uploaded content.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

from django.utils import timezone

from apps.audit.service import record as audit
from apps.publishing.models import Asset
from apps.repositories.service import GitError, repo_for_project

MAX_SIZE = 25 * 1024 * 1024   # 25 MB

# Allowed extensions per kind — the whitelist IS the safety boundary.
ALLOWED = {
    Asset.KIND_IMAGE: {"png", "jpg", "jpeg", "gif", "webp", "svg"},
    Asset.KIND_ICON: {"png", "svg", "ico"},
    Asset.KIND_VIDEO: {"mp4", "webm"},
    Asset.KIND_DOCUMENT: {"pdf"},
    Asset.KIND_FONT: {"woff", "woff2", "ttf", "otf"},
}
# First kind wins for shared extensions (png → image, not icon).
_EXT_KIND: dict[str, str] = {}
for _kind, _exts in ALLOWED.items():
    for _ext in _exts:
        _EXT_KIND.setdefault(_ext, _kind)
_PILLOW_EXT = {"png", "jpg", "jpeg", "gif", "webp"}   # raster formats Pillow handles


class AssetError(Exception):
    pass


def _sanitize(name: str) -> str:
    name = Path(name or "").name                       # strip any path
    name = name.replace(" ", "-")
    name = re.sub(r"[^A-Za-z0-9._-]", "", name)
    name = re.sub(r"\.{2,}", ".", name).strip("._-")   # no ".." tricks
    return name or "file"


def _ext(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _repo_write_bytes(repo, rel: str, data: bytes):
    root = repo.path.resolve()
    dest = (repo.path / rel).resolve()
    if dest != root and root not in dest.parents:
        raise AssetError("Path escapes the repository.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def _commit(repo, message):
    try:
        return repo.commit(message)
    except GitError:
        return ""


def _image_dims(data: bytes, ext: str):
    if ext not in _PILLOW_EXT:
        return None, None
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            im.verify()                                # confirms it's a real image
        with Image.open(io.BytesIO(data)) as im:
            return im.width, im.height
    except Exception as exc:
        raise AssetError(f"That file isn't a valid image: {exc}")


def store_asset(website, *, filename, data: bytes, content_type="", kind=None, user=None) -> Asset:
    if len(data) > MAX_SIZE:
        raise AssetError(f"File is too large (max {MAX_SIZE // (1024 * 1024)} MB).")
    if not data:
        raise AssetError("The file is empty.")
    safe = _sanitize(filename)
    ext = _ext(safe)
    if ext not in _EXT_KIND:
        raise AssetError(f".{ext or '?'} files aren't allowed.")
    kind = kind or _EXT_KIND[ext]
    if ext not in ALLOWED.get(kind, set()):
        raise AssetError(f".{ext} is not a valid {kind} file.")

    width, height = _image_dims(data, ext)

    repo = repo_for_project(website.project)
    if not repo.is_initialized:
        repo.init()

    rel = _unique_path(website, repo, safe)
    _repo_write_bytes(repo, rel, data)
    commit = _commit(repo, f"Add asset {rel}")

    asset = Asset.objects.create(
        website=website, path=rel, original_name=safe, kind=kind,
        content_type=content_type or "", size=len(data), width=width, height=height,
        created_by=user,
    )
    audit("asset.upload", actor=user, organization=website.project.organization,
          target=f"asset:{asset.id}", summary=rel, metadata={"commit": commit})
    return asset


def _unique_path(website, repo, safe: str) -> str:
    base = f"assets/{safe}"
    if not website.assets.filter(path=base).exists() and not (repo.path / base).exists():
        return base
    stem, dot, ext = safe.rpartition(".")
    stem = stem or safe
    n = 2
    while True:
        candidate = f"assets/{stem}-{n}{dot}{ext}" if dot else f"assets/{stem}-{n}"
        if not website.assets.filter(path=candidate).exists() and not (repo.path / candidate).exists():
            return candidate
        n += 1


def read_bytes(asset: Asset) -> bytes:
    repo = repo_for_project(asset.website.project)
    return (repo.path / asset.path).read_bytes()


def replace_asset(asset: Asset, *, data: bytes, user=None) -> Asset:
    ext = _ext(asset.path)
    if ext in _PILLOW_EXT:
        asset.width, asset.height = _image_dims(data, ext)
    repo = repo_for_project(asset.website.project)
    _repo_write_bytes(repo, asset.path, data)
    _commit(repo, f"Replace asset {asset.path}")
    asset.size = len(data)
    asset.save(update_fields=["size", "width", "height"])
    audit("asset.replace", actor=user, organization=asset.website.project.organization,
          target=f"asset:{asset.id}", summary=asset.path)
    return asset


def resize_image(asset: Asset, *, width: int, user=None) -> Asset:
    """Real Pillow resize, preserving aspect ratio. Images only."""
    _require_raster(asset)
    if width < 1 or width > 8000:
        raise AssetError("Width must be between 1 and 8000 pixels.")
    from PIL import Image
    repo = repo_for_project(asset.website.project)
    with Image.open(repo.path / asset.path) as im:
        ratio = width / im.width
        size = (width, max(1, round(im.height * ratio)))
        out = im.resize(size)
        buf = io.BytesIO()
        out.save(buf, format=im.format)
    data = buf.getvalue()
    _repo_write_bytes(repo, asset.path, data)
    _commit(repo, f"Resize asset {asset.path} to {width}px")
    asset.width, asset.height = size
    asset.size = len(data)
    asset.save(update_fields=["width", "height", "size"])
    audit("asset.resize", actor=user, organization=asset.website.project.organization,
          target=f"asset:{asset.id}", summary=f"{size[0]}x{size[1]}")
    return asset


def compress_image(asset: Asset, *, quality: int = 75, user=None) -> Asset:
    """Real Pillow re-encode at lower quality / optimized. Images only."""
    _require_raster(asset)
    quality = max(10, min(95, quality))
    from PIL import Image
    repo = repo_for_project(asset.website.project)
    with Image.open(repo.path / asset.path) as im:
        buf = io.BytesIO()
        fmt = im.format
        params = {"optimize": True}
        if fmt in ("JPEG", "WEBP"):
            params["quality"] = quality
        im.save(buf, format=fmt, **params)
    data = buf.getvalue()
    before = asset.size
    _repo_write_bytes(repo, asset.path, data)
    _commit(repo, f"Compress asset {asset.path}")
    asset.size = len(data)
    asset.save(update_fields=["size"])
    audit("asset.compress", actor=user, organization=asset.website.project.organization,
          target=f"asset:{asset.id}", summary=f"{before}→{len(data)} bytes")
    return asset


def delete_asset(asset: Asset, *, user=None) -> None:
    repo = repo_for_project(asset.website.project)
    target = (repo.path / asset.path)
    org, path = asset.website.project.organization, asset.path
    if target.exists():
        target.unlink()
        _commit(repo, f"Delete asset {path}")
    asset.delete()
    audit("asset.delete", actor=user, organization=org, target="asset", summary=path)


def _require_raster(asset: Asset):
    if _ext(asset.path) not in _PILLOW_EXT:
        raise AssetError("Only raster images (PNG/JPG/GIF/WEBP) can be resized or compressed.")
