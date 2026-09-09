"""AI operations advisor (spec §37).

BUILD → OPERATE → IMPROVE. After a site is published, this inspects the REAL
operational signals DevForge already collects — monitoring (response time, incidents),
analytics (traffic, conversion), asset sizes, page weight, the SEO and accessibility
audits, publish state and domain/SSL status — and turns them into prioritized,
explained findings with a concrete recommended action.

HONESTY: every finding is derived from actual measured data (never invented
metrics). Fixes that mean a code change go through DevForge's existing approval-gated
ChangeRequest loop — nothing is auto-applied. Tool-level fixes (optimize an image,
generate SEO, add a form) link to the real tool that does it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from apps.repositories.service import repo_for_project

LARGE_IMAGE = 500 * 1024        # 500 KB
HUGE_IMAGE = 2 * 1024 * 1024    # 2 MB
LARGE_PAGE = 250 * 1024         # 250 KB of HTML
SLOW_MS = 500

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class Finding:
    key: str
    area: str
    severity: str          # high / medium / low
    title: str
    explanation: str
    recommendation: str
    action: dict           # {"type":"link","url_name":..,"label":..} or {"type":"change","label":..}


def analyze(website) -> list[Finding]:
    f: list[Finding] = []
    _reliability(website, f)
    _performance(website, f)
    _seo(website, f)
    _accessibility(website, f)
    _conversion(website, f)
    _domain(website, f)
    f.sort(key=lambda x: SEVERITY_ORDER.get(x.severity, 3))
    return f


def _link(url_name, label):
    return {"type": "link", "url_name": url_name, "label": label}


def _change(label):
    return {"type": "change", "label": label}


def _reliability(website, out):
    from apps.publishing import monitor
    current = website.current
    if current is None:
        return
    summary = monitor.uptime_summary(website, days=7)
    if summary["current"] == "down":
        out.append(Finding(
            "site_down", "Reliability", "high", "Your site is currently down",
            f"The latest health check failed: {summary['current_detail']}",
            "Re-publish the site or roll back to the last healthy version.",
            _link("dashboard:publish_center", "Open Release Center")))
    elif summary["incidents"]:
        out.append(Finding(
            "downtime", "Reliability", "high",
            f"{summary['incidents']} recent incident(s)",
            f"Health checks recorded {summary['incidents']} period(s) of downtime in the last 7 days.",
            "Review the monitoring timeline and re-publish if needed.",
            _link("dashboard:monitoring", "Open monitoring")))
    if summary["avg_response_ms"] and summary["avg_response_ms"] > SLOW_MS:
        out.append(Finding(
            "slow_serve", "Performance", "medium", "Serving is slower than expected",
            f"Average serve time is {summary['avg_response_ms']}ms.",
            "Reduce page weight and compress large assets.",
            _link("dashboard:monitoring", "Open monitoring")))


def _performance(website, out):
    # Large images (real asset sizes).
    imgs = [a for a in website.assets.all() if a.is_image]
    heavy = [a for a in imgs if a.size >= LARGE_IMAGE]
    if heavy:
        worst = max(a.size for a in heavy)
        sev = "high" if worst >= HUGE_IMAGE else "medium"
        out.append(Finding(
            "large_images", "Performance", sev,
            f"{len(heavy)} large image(s) slowing page loads",
            f"The biggest is {worst // 1024} KB. Large images are the most common cause of slow pages.",
            "Compress or resize these images.",
            _link("dashboard:assets", "Optimize images")))
    # Large HTML pages (real file sizes).
    repo = repo_for_project(website.project)
    if repo.is_initialized:
        big = []
        for rel in repo.list_files():
            if rel.endswith(".html"):
                try:
                    if (Path(repo.path) / rel).stat().st_size >= LARGE_PAGE:
                        big.append(rel)
                except OSError:
                    pass
        if big:
            out.append(Finding(
                "page_weight", "Performance", "medium",
                f"{len(big)} page(s) are heavy",
                f"These pages are over {LARGE_PAGE // 1024} KB of HTML: {', '.join(big[:3])}.",
                "Trim inline assets and split large pages; DevForge can propose a fix.",
                _change("Create a performance fix")))


def _seo(website, out):
    from apps.publishing import seo
    audits = seo.audit_pages(website)
    if not audits:
        return
    failing = sum(1 for a in audits for f in a.findings
                  if f["key"] in ("title", "description") and f["status"] == "fail")
    if failing:
        out.append(Finding(
            "seo_gaps", "SEO", "medium", f"{failing} page(s) missing title or description",
            "Missing titles/descriptions hurt how your site appears in search and social shares.",
            "Generate and apply SEO metadata.",
            _link("dashboard:publish_center", "Open SEO tools")))


def _accessibility(website, out):
    from apps.publishing import accessibility as a11y
    audits = a11y.audit_pages(website)
    fails = sum(1 for a in audits for f in a.findings if f["status"] == "fail")
    if fails:
        out.append(Finding(
            "a11y", "Accessibility", "medium", f"{fails} accessibility issue(s) to fix",
            "Automated checks found problems like missing alt text or unlabeled form fields.",
            "Review the accessibility report and address the failing checks.",
            _link("dashboard:accessibility", "Open accessibility")))


def _conversion(website, out):
    from apps.publishing import analytics
    data = analytics.summary(website, days=30)
    has_form = website.forms.filter(active=True).exists()
    if data["sessions"] >= 20 and not has_form:
        out.append(Finding(
            "no_capture", "Growth", "medium", "Visitors, but no way to capture leads",
            f"{data['sessions']} session(s) in 30 days and no form on the site.",
            "Add a contact or quote form so visitors can reach you.",
            _link("dashboard:publish_center", "Add a form")))
    elif has_form and data["sessions"] >= 50 and data["conversion"] < 1.0:
        out.append(Finding(
            "low_conversion", "Growth", "low", "Low form conversion",
            f"Conversion is {data['conversion']}% over {data['sessions']} sessions.",
            "Make your form more prominent and simplify its fields.",
            _link("dashboard:analytics", "Open analytics")))


def _domain(website, out):
    for d in website.domains.all():
        if d.verification_status != "verified":
            out.append(Finding(
                "domain_pending", "Setup", "low", f"Finish setting up {d.hostname}",
                "The domain's DNS records aren't verified yet, so it can't go live.",
                "Add the DNS records and verify the domain.",
                _link("dashboard:publish_center", "Finish domain setup")))
            break


def summary_line(findings: list[Finding]) -> str:
    if not findings:
        return "Everything looks healthy — no operational issues detected right now."
    highs = sum(1 for f in findings if f.severity == "high")
    parts = [f"{len(findings)} thing(s) to look at"]
    if highs:
        parts.append(f"{highs} need attention now")
    return "; ".join(parts) + "."
