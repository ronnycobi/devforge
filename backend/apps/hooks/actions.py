"""Hook action handlers — each returns (status, detail) where status is pass/fail/skip.

They reuse real DevForge services (the test runner, the security scanner). None
fabricates a result: if there's nothing to check, the handler returns 'skip'.
"""
from __future__ import annotations

_SKIP_EXT = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".woff", ".woff2")


def run_tests(project, config) -> tuple[str, str]:
    from apps.codegen.service import run_repo_tests
    r = run_repo_tests(project)
    passed = r.get("passed")
    if passed is None:
        return "skip", r.get("note", "nothing to test")
    if passed:
        return "pass", f"{r.get('ran', 0)} test(s) passed"
    return "fail", f"{r.get('failures', 0)} failure(s), {r.get('errors', 0)} error(s)"


def security_scan(project, config) -> tuple[str, str]:
    from apps.repositories.service import repo_for_project
    from apps.security.scanner import Severity, scan_files, summarize
    repo = repo_for_project(project)
    if not repo.is_initialized:
        return "skip", "no repository"
    files = {}
    for rel in repo.list_files():
        if rel.lower().endswith(_SKIP_EXT):
            continue
        try:
            files[rel] = (repo.path / rel).read_text()
        except (OSError, UnicodeDecodeError):
            continue
    if not files:
        return "skip", "no code to scan"
    findings = scan_files(files)
    summary = summarize(findings)
    high = summary.get(Severity.HIGH, 0)
    if high:
        return "fail", f"{high} high-severity finding(s)"
    return "pass", f"scanned {len(files)} file(s), no high-severity findings"


def manual_gate(project, config) -> tuple[str, str]:
    # A hard human sign-off gate: fails (blocks) until someone explicitly clears it.
    if config and config.get("cleared"):
        return "pass", "manually cleared"
    return "fail", config.get("message", "awaiting manual sign-off") if config else "awaiting manual sign-off"


ACTIONS = {
    "run_tests": run_tests,
    "security_scan": security_scan,
    "manual_gate": manual_gate,
}
