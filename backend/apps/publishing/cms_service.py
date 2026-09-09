"""Content management (spec §25).

Opt-in CMS: a website can add content collections (blog, FAQs, services, team, …),
edit items, and GENERATE real HTML pages from them into the project's repo — so the
content publishes and is served like the rest of the site. The generated HTML is
clean and accessible (lang attribute, a single h1, landmarks, alt text on images),
which also keeps the accessibility and SEO checks happy.

A CMS is only created when the customer asks for one; simple static sites are left
alone (spec §25).
"""
from __future__ import annotations

import html as html_lib
import re

from django.utils.text import slugify

from apps.audit.service import record as audit
from apps.publishing.models import ContentCollection, ContentItem
from apps.repositories.service import GitError, repo_for_project


class CmsError(Exception):
    pass


def create_collection(website, *, kind="blog", name=None, user=None) -> ContentCollection:
    base = slugify(name or kind) or "content"
    slug, n = base, 1
    while website.collections.filter(slug=slug).exists():
        n += 1
        slug = f"{base}-{n}"
    coll = ContentCollection.objects.create(
        website=website, slug=slug, name=name or dict(ContentCollection.KINDS).get(kind, "Content"),
        kind=kind,
    )
    audit("cms.collection", actor=user, organization=website.project.organization,
          target=f"collection:{coll.id}", summary=coll.name)
    return coll


def add_item(collection, *, title, subtitle="", body="", image="", published=True, user=None) -> ContentItem:
    base = slugify(title) or "item"
    slug, n = base, 1
    while collection.items.filter(slug=slug).exists():
        n += 1
        slug = f"{base}-{n}"
    return ContentItem.objects.create(
        collection=collection, slug=slug, title=title, subtitle=subtitle,
        body=body, image=image, published=published,
        order=collection.items.count(),
    )


# --- HTML generation -----------------------------------------------------------
def _p(body: str) -> str:
    """Escape text and wrap paragraphs (blank-line separated)."""
    blocks = re.split(r"\n\s*\n", (body or "").strip())
    return "\n".join(f"<p>{html_lib.escape(b).strip()}</p>" for b in blocks if b.strip())


def _doc(title: str, main: str) -> str:
    t = html_lib.escape(title)
    return (
        f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{t}</title></head><body>"
        f"<header><nav><a href=\"/\">Home</a></nav></header>"
        f"<main>{main}</main></body></html>"
    )


def _img(item) -> str:
    if not item.image:
        return ""
    return f'<img src="{html_lib.escape(item.image)}" alt="{html_lib.escape(item.title)}">'


def render_collection(collection) -> dict:
    """Return {repo_path: html} for a collection's published items."""
    items = list(collection.items.filter(published=True))
    kind, slug, name = collection.kind, collection.slug, collection.name
    files: dict[str, str] = {}
    if not items:
        return files   # nothing published → generate no (empty) pages

    if kind in ("blog", "article"):
        cards = "".join(
            f'<article><h2><a href="/{slug}/{it.slug}.html">{html_lib.escape(it.title)}</a></h2>'
            f'{f"<p>{html_lib.escape(it.subtitle)}</p>" if it.subtitle else ""}</article>'
            for it in items
        )
        files[f"{slug}/index.html"] = _doc(name, f"<h1>{html_lib.escape(name)}</h1>{cards}")
        for it in items:
            body = (f"<h1>{html_lib.escape(it.title)}</h1>"
                    f'{f"<p>{html_lib.escape(it.subtitle)}</p>" if it.subtitle else ""}'
                    f"{_img(it)}{_p(it.body)}")
            files[f"{slug}/{it.slug}.html"] = _doc(it.title, body)

    elif kind == "faq":
        qa = "".join(
            f"<section><h2>{html_lib.escape(it.title)}</h2>{_p(it.body)}</section>"
            for it in items
        )
        files[f"{slug}.html"] = _doc(name, f"<h1>{html_lib.escape(name)}</h1>{qa}")

    elif kind == "page":
        for it in items:
            body = f"<h1>{html_lib.escape(it.title)}</h1>{_img(it)}{_p(it.body)}"
            files[f"{it.slug}.html"] = _doc(it.title, body)

    else:  # service / team / testimonial / product / project → one section page
        cards = "".join(
            f"<article>{_img(it)}<h2>{html_lib.escape(it.title)}</h2>"
            f'{f"<p><strong>{html_lib.escape(it.subtitle)}</strong></p>" if it.subtitle else ""}'
            f"{_p(it.body)}</article>"
            for it in items
        )
        files[f"{slug}.html"] = _doc(name, f"<h1>{html_lib.escape(name)}</h1>{cards}")

    return files


def generate(website, *, user=None) -> dict:
    """Render every collection into HTML in the repo and commit (spec §25)."""
    repo = repo_for_project(website.project)
    if not repo.is_initialized:
        repo.init()
    files: dict[str, str] = {}
    for coll in website.collections.all():
        files.update(render_collection(coll))
    if not files:
        raise CmsError("No published content to generate yet.")
    repo.write_files(files)
    try:
        commit = repo.commit("Generate CMS content pages")
    except GitError:
        commit = ""
    audit("cms.generate", actor=user, organization=website.project.organization,
          target=f"website:{website.id}", summary=f"{len(files)} page(s)",
          metadata={"commit": commit})
    return {"pages": len(files), "paths": sorted(files), "commit": commit}
