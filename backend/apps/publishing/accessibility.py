"""Accessibility checks (spec §30).

Automated STATIC analysis of the site's built HTML: it reports what it can actually
detect — missing alt text, heading structure, the html lang attribute, landmarks,
unlabeled form fields, empty interactive controls, positive tabindex, and focus
removal in CSS. Things that genuinely need a rendered page (full colour contrast,
real keyboard navigation) are reported as "needs manual review", never as a pass.

DevForge never claims guaranteed accessibility compliance (spec §30) — it surfaces
concrete findings a human can act on.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from apps.repositories.service import repo_for_project


@dataclass
class PageA11y:
    path: str
    findings: list[dict] = field(default_factory=list)


def _finding(key, label, status, detail=""):
    return {"key": key, "label": label, "status": status, "detail": detail}


def _pages(repo):
    return sorted(f for f in (repo.list_files() if repo.is_initialized else []) if f.endswith(".html"))


def audit_pages(website) -> list[PageA11y]:
    repo = repo_for_project(website.project)
    out = []
    for path in _pages(repo):
        try:
            html = (Path(repo.path) / path).read_text(errors="ignore")
        except Exception:
            continue
        out.append(PageA11y(path=path, findings=_check(html)))
    return out


def _check(html: str) -> list[dict]:
    f = []
    f.append(_lang(html))
    f.append(_alt(html))
    f.append(_headings(html))
    f.append(_landmarks(html))
    f.append(_labels(html))
    f.append(_empty_controls(html))
    f.append(_tabindex(html))
    f.append(_focus(html))
    f.append(_contrast(html))
    return f


def _lang(html):
    m = re.search(r"<html\b[^>]*>", html, re.I)
    ok = bool(m and re.search(r'\blang\s*=\s*["\']?[a-z]', m.group(0), re.I))
    return _finding("lang", "Language attribute", "ok" if ok else "fail",
                    "" if ok else "<html> has no lang attribute.")


def _alt(html):
    imgs = re.findall(r"<img\b[^>]*>", html, re.I)
    missing = sum(1 for t in imgs if not re.search(r'\balt\s*=', t, re.I))
    if not imgs:
        return _finding("alt", "Image alt text", "ok", "No images.")
    return _finding("alt", "Image alt text", "ok" if missing == 0 else "fail",
                    "" if missing == 0 else f"{missing} image(s) without alt.")


def _headings(html):
    levels = [int(m.group(1)) for m in re.finditer(r"<h([1-6])\b", html, re.I)]
    if not levels:
        return _finding("headings", "Heading structure", "warn", "No headings found.")
    issues = []
    if levels[0] != 1:
        issues.append("first heading isn't <h1>")
    if levels.count(1) == 0:
        issues.append("no <h1>")
    elif levels.count(1) > 1:
        issues.append("multiple <h1>")
    prev = levels[0]
    for lvl in levels[1:]:
        if lvl - prev > 1:
            issues.append(f"skips from h{prev} to h{lvl}")
            break
        prev = lvl
    return _finding("headings", "Heading structure", "ok" if not issues else "warn",
                    "; ".join(issues))


def _landmarks(html):
    has_main = bool(re.search(r"<main\b", html, re.I)) or 'role="main"' in html.lower()
    has_nav = bool(re.search(r"<nav\b", html, re.I)) or 'role="navigation"' in html.lower()
    if has_main and has_nav:
        return _finding("landmarks", "Landmarks (main/nav)", "ok")
    missing = ", ".join(m for m, ok in [("<main>", has_main), ("<nav>", has_nav)] if not ok)
    return _finding("landmarks", "Landmarks (main/nav)", "warn", f"Missing {missing}.")


def _labels(html):
    label_fors = set(re.findall(r'<label\b[^>]*\bfor\s*=\s*["\']([^"\']+)', html, re.I))
    unlabeled = 0
    for tag in re.findall(r"<(?:input|select|textarea)\b[^>]*>", html, re.I):
        itype = (re.search(r'\btype\s*=\s*["\']?([a-z]+)', tag, re.I) or [None, "text"])[1].lower()
        if itype in ("hidden", "submit", "button", "reset", "image"):
            continue
        has_aria = bool(re.search(r'\baria-label(ledby)?\s*=', tag, re.I)) or bool(re.search(r'\btitle\s*=', tag, re.I))
        idm = re.search(r'\bid\s*=\s*["\']([^"\']+)', tag, re.I)
        has_label = bool(idm and idm.group(1) in label_fors)
        if not (has_aria or has_label):
            unlabeled += 1
    return _finding("labels", "Form field labels", "ok" if unlabeled == 0 else "fail",
                    "" if unlabeled == 0 else f"{unlabeled} field(s) with no label.")


def _empty_controls(html):
    empty = 0
    for m in re.finditer(r"<(button|a)\b([^>]*)>(.*?)</\1>", html, re.I | re.S):
        attrs, inner = m.group(2), m.group(3)
        text = re.sub(r"<[^>]+>", "", inner).strip()
        has_aria = bool(re.search(r'\baria-label(ledby)?\s*=', attrs, re.I)) or bool(re.search(r'\btitle\s*=', attrs, re.I))
        has_img_alt = bool(re.search(r'<img\b[^>]*\balt\s*=\s*["\'][^"\']+', inner, re.I))
        if m.group(1).lower() == "a" and not re.search(r'\bhref\s*=', attrs, re.I):
            continue  # anchors without href aren't interactive
        if not text and not has_aria and not has_img_alt:
            empty += 1
    return _finding("controls", "Buttons & links have text", "ok" if empty == 0 else "warn",
                    "" if empty == 0 else f"{empty} control(s) with no accessible name.")


def _tabindex(html):
    positive = [t for t in re.findall(r'\btabindex\s*=\s*["\']?(\d+)', html, re.I) if int(t) > 0]
    return _finding("tabindex", "Tab order", "ok" if not positive else "warn",
                    "" if not positive else f"{len(positive)} positive tabindex (disrupts tab order).")


def _focus(html):
    # Removing focus outlines without a replacement is a keyboard-a11y problem.
    removed = bool(re.search(r"outline\s*:\s*(none|0)\b", html, re.I))
    return _finding("focus", "Focus visibility", "warn" if removed else "manual",
                    "Focus outline removed in CSS — ensure a visible focus style remains."
                    if removed else "Keyboard focus needs a quick manual check.")


def _contrast(html):
    # Best-effort on inline color+background pairs; otherwise honestly manual.
    ratios = []
    for tag in re.findall(r'style\s*=\s*["\']([^"\']+)["\']', html, re.I):
        fg = re.search(r"(?<!-)\bcolor\s*:\s*([^;]+)", tag, re.I)
        bg = re.search(r"background(?:-color)?\s*:\s*([^;]+)", tag, re.I)
        if fg and bg:
            c1, c2 = _parse_color(fg.group(1)), _parse_color(bg.group(1))
            if c1 and c2:
                ratios.append(_contrast_ratio(c1, c2))
    if not ratios:
        return _finding("contrast", "Colour contrast", "manual",
                        "Contrast needs a rendered check (computed CSS colours).")
    worst = min(ratios)
    if worst < 4.5:
        return _finding("contrast", "Colour contrast", "warn",
                        f"An inline colour pair is {worst:.1f}:1 (below 4.5:1).")
    return _finding("contrast", "Colour contrast", "ok", f"Inline pairs ≥ {worst:.1f}:1.")


def _parse_color(text):
    text = text.strip().lower()
    m = re.match(r"#([0-9a-f]{3})$", text)
    if m:
        return tuple(int(c * 2, 16) for c in m.group(1))
    m = re.match(r"#([0-9a-f]{6})$", text)
    if m:
        h = m.group(1)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = re.match(r"rgba?\(([^)]+)\)", text)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")[:3]]
        try:
            return tuple(int(float(p)) for p in parts)
        except ValueError:
            return None
    return {"white": (255, 255, 255), "black": (0, 0, 0)}.get(text)


def _rel_luminance(rgb):
    def chan(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(c1, c2):
    l1, l2 = _rel_luminance(c1), _rel_luminance(c2)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def score(audits: list[PageA11y]) -> int:
    weights = {"ok": 1.0, "warn": 0.5, "manual": 0.5, "fail": 0.0}
    total = sum(len(a.findings) for a in audits)
    if not total:
        return 0
    got = sum(weights.get(f["status"], 0.0) for a in audits for f in a.findings)
    return round(100 * got / total)
