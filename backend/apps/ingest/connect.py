"""Fetch a repository archive from GitHub or GitLab for import.

Security posture (see CLAUDE.md):
- SSRF-safe by construction: the request host is a fixed allow-listed API host,
  never a user-supplied URL. The owner/repo/ref are validated against a strict
  slug pattern and URL-encoded, so they cannot redirect the request elsewhere.
- Tokens are used transiently for the one download and never stored or logged.
- The download is size-capped (compressed) before the existing extract_zip caps
  apply, so a hostile or huge repo cannot exhaust memory or disk.
- Failure is honest: network, auth, or not-found errors raise ConnectError with
  a clear message rather than fabricating a result.
"""
from __future__ import annotations

import io
import re
from urllib.parse import quote

import requests

from apps.ingest.analyzer import IngestError

PROVIDERS = {"github": "GitHub", "gitlab": "GitLab"}
MAX_DOWNLOAD_BYTES = 40 * 1024 * 1024  # compressed archive cap
_TIMEOUT = 20  # seconds
# owner/repo path segments: letters, digits, dot, dash, underscore (GitHub/GitLab rules).
_SEG = re.compile(r"^[A-Za-z0-9._-]+$")
# a git ref (branch/tag/sha): the above plus '/' for grouped branches like feature/x.
_REF = re.compile(r"^[A-Za-z0-9._/-]+$")


class ConnectError(IngestError):
    pass


def _valid(owner: str, repo: str, ref: str) -> None:
    if not (_SEG.match(owner or "") and _SEG.match(repo or "")):
        raise ConnectError("Enter a valid owner and repository name.")
    if ref and (not _REF.match(ref) or ".." in ref):
        raise ConnectError("That branch/tag name isn't valid.")


def parse_repo(text: str) -> tuple[str, str]:
    """Accept 'owner/repo', a full https URL, or a git@ URL → (owner, repo)."""
    text = (text or "").strip()
    text = re.sub(r"^https?://[^/]+/", "", text)          # strip https://host/
    text = re.sub(r"^git@[^:]+:", "", text)               # strip git@host:
    text = re.sub(r"\.git$", "", text)                    # strip trailing .git
    text = text.strip("/")
    parts = [p for p in text.split("/") if p]
    if len(parts) < 2:
        raise ConnectError("Repository must look like owner/repo.")
    return parts[0], parts[1]


def _download(url: str, headers: dict) -> io.BytesIO:
    try:
        resp = requests.get(url, headers=headers, stream=True, timeout=_TIMEOUT,
                            allow_redirects=True)
    except requests.RequestException as exc:
        raise ConnectError(f"Couldn't reach the repository host: {exc}") from exc

    if resp.status_code in (401, 403):
        raise ConnectError("Access denied. For a private repo, provide a valid access token.")
    if resp.status_code == 404:
        raise ConnectError("Repository or branch not found. Check the name and that it's accessible.")
    if resp.status_code != 200:
        raise ConnectError(f"The host returned HTTP {resp.status_code}.")

    buf = io.BytesIO()
    total = 0
    for chunk in resp.iter_content(chunk_size=65536):
        total += len(chunk)
        if total > MAX_DOWNLOAD_BYTES:
            raise ConnectError("Repository archive is too large (over 40 MB compressed).")
        buf.write(chunk)
    buf.seek(0)
    return buf


def fetch_repo_archive(provider: str, owner: str, repo: str,
                       ref: str = "", token: str = "") -> io.BytesIO:
    """Return a BytesIO of the repo's zip archive, ready for extract_zip."""
    if provider not in PROVIDERS:
        raise ConnectError("Unsupported provider.")
    _valid(owner, repo, ref)

    if provider == "github":
        # Fixed host; ref is optional (default branch when empty).
        path = f"{quote(owner, safe='')}/{quote(repo, safe='')}/zipball"
        url = f"https://api.github.com/repos/{path}"
        if ref:
            url += f"/{quote(ref, safe='')}"
        headers = {"Accept": "application/vnd.github+json",
                   "User-Agent": "DevForge-Ingest"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
    else:  # gitlab
        project = quote(f"{owner}/{repo}", safe="")  # URL-encoded project path
        url = f"https://gitlab.com/api/v4/projects/{project}/repository/archive.zip"
        if ref:
            url += f"?sha={quote(ref, safe='')}"
        headers = {"User-Agent": "DevForge-Ingest"}
        if token:
            headers["PRIVATE-TOKEN"] = token

    return _download(url, headers)
