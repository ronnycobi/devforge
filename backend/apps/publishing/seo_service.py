"""SEO orchestration (spec §27).

generate_drafts(): draft metadata for every real page (AI or deterministic) as
editable, unapproved PageSeo rows. apply_seo(): write genuine sitemap.xml + robots.txt
and inject the APPROVED metadata into the actual page HTML in the repo, then commit —
a real code change, done only on the customer's explicit apply, never automatically.
"""
from __future__ import annotations

from django.utils import timezone

from apps.audit.service import record as audit
from apps.publishing import seo
from apps.publishing.models import PageSeo, SeoConfig
from apps.repositories.service import GitError, repo_for_project


class SeoServiceError(Exception):
    pass


def ensure_config(website) -> SeoConfig:
    config = getattr(website, "seo", None)
    if config:
        return config
    return SeoConfig.objects.create(
        website=website, title_suffix=f" · {website.project.name}"[:120],
    )


def generate_drafts(website, *, user=None) -> list[PageSeo]:
    config = ensure_config(website)
    audits = seo.audit_pages(website)
    drafts = []
    for a in audits:
        meta = seo.generate_meta(website, a.path)
        page, _ = PageSeo.objects.update_or_create(
            config=config, path=a.path,
            defaults={
                "title": meta.get("title", "")[:200],
                "description": meta.get("description", "")[:320],
                "og_title": meta.get("og_title", "")[:200],
                "og_description": meta.get("og_description", "")[:320],
                "canonical": meta.get("canonical", "")[:1024],
                "ai_generated": True, "approved": False, "applied": False,
            },
        )
        drafts.append(page)
    audit("seo.generate", actor=user, organization=website.project.organization,
          target=f"website:{website.id}", summary=f"{len(drafts)} page(s)")
    return drafts


def approve_page(page: PageSeo, *, user=None) -> PageSeo:
    page.approved = True
    page.save(update_fields=["approved", "updated_at"])
    return page


def apply_seo(website, *, user=None) -> dict:
    """Write sitemap.xml + robots.txt and inject APPROVED page metadata into the real
    HTML, then commit. Only approved pages are applied."""
    config = ensure_config(website)
    repo = repo_for_project(website.project)
    if not repo.is_initialized or not repo.list_files():
        raise SeoServiceError("There's no built site to apply SEO to yet.")

    files: dict[str, str] = {}
    if config.sitemap_enabled:
        files["sitemap.xml"] = seo.build_sitemap(website)
    files["robots.txt"] = seo.build_robots(website, allow=config.robots_allow)

    applied_pages = 0
    for page in config.pages.filter(approved=True):
        try:
            html = (repo.path / page.path).read_text(errors="ignore")
        except Exception:
            continue
        new_html = seo.apply_meta_to_html(html, {
            "title": page.title, "description": page.description,
            "canonical": page.canonical, "og_title": page.og_title,
            "og_description": page.og_description,
        })
        if new_html != html:
            files[page.path] = new_html
        page.applied = True
        page.save(update_fields=["applied", "updated_at"])
        applied_pages += 1

    repo.write_files(files)
    try:
        commit = repo.commit("Apply SEO metadata, sitemap and robots.txt")
    except GitError:
        commit = ""   # nothing changed on disk (already applied) — not an error

    config.applied_at = timezone.now()
    config.save(update_fields=["applied_at", "updated_at"])
    audit("seo.apply", actor=user, organization=website.project.organization,
          target=f"website:{website.id}",
          summary=f"{applied_pages} page(s), sitemap+robots", metadata={"commit": commit})
    return {"pages": applied_pages, "sitemap": config.sitemap_enabled, "commit": commit}
