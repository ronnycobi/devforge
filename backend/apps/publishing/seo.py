"""SEO engine (spec §27).

Works on the site's REAL built pages: it audits the actual HTML, drafts metadata
from real page content (AI when a model is available, otherwise a deterministic
draft from headings/filename), and produces genuine sitemap.xml / robots.txt. AI
output is a draft the customer edits and approves — nothing is applied to the pages
until an explicit apply step, and DevForge never guarantees rankings (spec §27).
"""
from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

from apps.repositories.service import repo_for_project


@dataclass
class PageAudit:
    path: str
    title: str = ""
    findings: list[dict] = field(default_factory=list)   # {key,label,status,detail}

    @property
    def ok_count(self) -> int:
        return sum(1 for f in self.findings if f["status"] == "ok")


def _html_pages(repo) -> list[str]:
    return sorted(f for f in (repo.list_files() if repo.is_initialized else []) if f.endswith(".html"))


def _read(repo, path) -> str:
    try:
        return (Path(repo.path) / path).read_text(errors="ignore")
    except Exception:
        return ""


# --- extraction ----------------------------------------------------------------
def _title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    return html_lib.unescape(m.group(1).strip()) if m else ""


def _first_h1(html: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else ""


def _first_paragraph(html: str) -> str:
    for m in re.finditer(r"<p[^>]*>(.*?)</p>", html, re.I | re.S):
        text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        if len(text) > 30:
            return text
    return ""


def _has_meta_description(html: str) -> bool:
    return bool(re.search(r'<meta[^>]+name=["\']description["\'][^>]*>', html, re.I))


def _has_canonical(html: str) -> bool:
    return bool(re.search(r'<link[^>]+rel=["\']canonical["\'][^>]*>', html, re.I))


def _has_og(html: str) -> bool:
    return bool(re.search(r'<meta[^>]+property=["\']og:', html, re.I))


def _images_missing_alt(html: str) -> int:
    imgs = re.findall(r"<img\b[^>]*>", html, re.I)
    return sum(1 for tag in imgs if not re.search(r'\balt\s*=', tag, re.I))


# --- audit ---------------------------------------------------------------------
def audit_pages(website) -> list[PageAudit]:
    repo = repo_for_project(website.project)
    audits: list[PageAudit] = []
    for path in _html_pages(repo):
        html = _read(repo, path)
        title = _title(html)
        f = []
        f.append(_finding("title", "Title tag", "ok" if title else "fail",
                          "" if title else "No <title>."))
        f.append(_finding("description", "Meta description",
                          "ok" if _has_meta_description(html) else "fail",
                          "" if _has_meta_description(html) else "Missing."))
        f.append(_finding("canonical", "Canonical URL",
                          "ok" if _has_canonical(html) else "warn",
                          "" if _has_canonical(html) else "No canonical link."))
        f.append(_finding("og", "Social metadata (Open Graph)",
                          "ok" if _has_og(html) else "warn",
                          "" if _has_og(html) else "No Open Graph tags."))
        f.append(_finding("h1", "Heading structure",
                          "ok" if _first_h1(html) else "warn",
                          "" if _first_h1(html) else "No <h1> found."))
        missing_alt = _images_missing_alt(html)
        f.append(_finding("alt", "Image alt text", "ok" if missing_alt == 0 else "warn",
                          "" if missing_alt == 0 else f"{missing_alt} image(s) without alt."))
        audits.append(PageAudit(path=path, title=title, findings=f))
    return audits


def _finding(key, label, status, detail=""):
    return {"key": key, "label": label, "status": status, "detail": detail}


def audit_score(audits: list[PageAudit]) -> int:
    weights = {"ok": 1.0, "warn": 0.5, "fail": 0.0}
    total = sum(len(a.findings) for a in audits)
    if not total:
        return 0
    got = sum(weights.get(f["status"], 0.0) for a in audits for f in a.findings)
    return round(100 * got / total)


# --- draft generation ----------------------------------------------------------
def _clip(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text[: n - 1].rstrip() + "…" if len(text) > n else text


def generate_meta(website, path: str, *, router=None) -> dict:
    """Draft title/description/OG for one page from its REAL content."""
    repo = repo_for_project(website.project)
    html = _read(repo, path)
    heading = _first_h1(html) or _slug_to_words(path)
    para = _first_paragraph(html)
    site = website.project.name

    draft = _try_ai(site, heading, para, router)
    if not draft:
        title = _clip(f"{heading} · {site}" if heading.lower() != site.lower() else site, 60)
        desc = _clip(para or f"{heading} at {site}.", 155)
        draft = {"title": title, "description": desc,
                 "og_title": _clip(heading or site, 60), "og_description": desc,
                 "source": "content"}
    draft["canonical"] = _page_url(website, path)
    return draft


def _try_ai(site, heading, para, router) -> dict | None:
    try:
        from apps.ai_providers.base import Message
        from apps.model_router.router import ModelRouter, RoutingRequest, TaskComplexity
        router = router or ModelRouter()
        system = (
            "You write SEO metadata. Given a page's site name, heading and intro text, "
            "return ONLY JSON with keys title (<=60 chars), description (<=155 chars), "
            "og_title, og_description. Base it strictly on the given content — invent "
            "nothing, and make no ranking claims."
        )
        prompt = f"Site: {site}\nHeading: {heading}\nIntro: {para or '(none)'}"
        resp = router.complete(RoutingRequest(complexity=TaskComplexity.LOW, task_type="seo"),
                               messages=[Message(role="user", content=prompt)],
                               system=system, max_tokens=300)
        m = re.search(r"\{.*\}", resp.text, re.S)
        if not m:
            return None
        import json
        data = json.loads(m.group(0))
        if not data.get("title") or not data.get("description"):
            return None
        data["source"] = resp.model
        return data
    except Exception:
        return None


# --- sitemap / robots ----------------------------------------------------------
def _page_url(website, path: str) -> str:
    base = f"https://{website.subdomain}.{settings.DEVFORGE_BASE_DOMAIN}"
    rel = "" if path == "index.html" else path
    return f"{base}/{rel}"


def build_sitemap(website) -> str:
    repo = repo_for_project(website.project)
    urls = "".join(
        f"  <url><loc>{html_lib.escape(_page_url(website, p))}</loc></url>\n"
        for p in _html_pages(repo)
    )
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{urls}</urlset>\n")


def build_robots(website, *, allow=True) -> str:
    base = f"https://{website.subdomain}.{settings.DEVFORGE_BASE_DOMAIN}"
    if allow:
        return f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n"
    return "User-agent: *\nDisallow: /\n"


# --- apply metadata into HTML (idempotent) -------------------------------------
def apply_meta_to_html(html: str, meta: dict) -> str:
    """Insert/replace title + description + canonical + OG in <head>. Idempotent:
    re-applying replaces DevForge-managed tags rather than duplicating them."""
    tags = _managed_tags(meta)
    # Remove any previously managed block, then existing title/description we manage.
    html = re.sub(r"\n?\s*<!-- devforge:seo -->.*?<!-- /devforge:seo -->", "", html, flags=re.S)
    block = "<!-- devforge:seo -->\n" + tags + "<!-- /devforge:seo -->"
    if re.search(r"</head>", html, re.I):
        return re.sub(r"</head>", block + "\n</head>", html, count=1, flags=re.I)
    # No head — prepend a minimal one.
    return f"<head>\n{block}\n</head>\n{html}"


def _managed_tags(meta: dict) -> str:
    e = html_lib.escape
    lines = []
    if meta.get("title"):
        lines.append(f"<title>{e(meta['title'])}</title>")
    if meta.get("description"):
        lines.append(f'<meta name="description" content="{e(meta["description"])}">')
    if meta.get("canonical"):
        lines.append(f'<link rel="canonical" href="{e(meta["canonical"])}">')
    if meta.get("og_title"):
        lines.append(f'<meta property="og:title" content="{e(meta["og_title"])}">')
    if meta.get("og_description"):
        lines.append(f'<meta property="og:description" content="{e(meta["og_description"])}">')
    return "".join(l + "\n" for l in lines)


def _slug_to_words(path: str) -> str:
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0].replace("-", " ").replace("_", " ")
    return stem.title() if stem and stem != "index" else "Home"
