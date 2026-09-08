"""Deterministic static security scanner for generated/imported code.

No model, no network — a focused set of high-signal rules over source text, so it
runs offline and never fabricates. It catches the classes DevForge must never
ship: hard-coded secrets, code/command injection sinks, unsafe deserialization,
and a few framework foot-guns. Rules are intentionally conservative (a quoted
literal for secrets, specific sink calls) to keep false positives low; it is a
safety net, not a replacement for review.

Findings are severity-ranked; a caller decides policy (e.g. block on HIGH).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath


class Severity:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


_ORDER = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}


@dataclass(frozen=True)
class Finding:
    severity: str
    category: str
    message: str
    path: str
    line: int
    evidence: str

    def as_dict(self) -> dict:
        return {
            "severity": self.severity, "category": self.category,
            "message": self.message, "path": self.path, "line": self.line,
            "evidence": self.evidence[:200],
        }


# (compiled regex, severity, category, message). Grouped by where they apply.
def _rx(p):
    return re.compile(p, re.IGNORECASE)


# Secrets + universal sinks — checked in every text file.
_COMMON_RULES = [
    (_rx(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
     Severity.HIGH, "secret", "Private key committed in source"),
    (_rx(r"\bAKIA[0-9A-Z]{16}\b"), Severity.HIGH, "secret", "AWS access key id in source"),
    (_rx(r"""(?:password|passwd|pwd|secret|api[_-]?key|apikey|access[_-]?token|auth[_-]?token|client[_-]?secret)\s*[:=]\s*['"][^'"\s]{6,}['"]"""),
     Severity.HIGH, "secret", "Hard-coded credential/secret literal"),
]

_PY_RULES = [
    (_rx(r"\beval\s*\("), Severity.HIGH, "code-injection", "Use of eval()"),
    (_rx(r"\bexec\s*\("), Severity.HIGH, "code-injection", "Use of exec()"),
    (_rx(r"\bos\.system\s*\("), Severity.HIGH, "command-injection", "os.system() shell call"),
    (_rx(r"shell\s*=\s*True"), Severity.HIGH, "command-injection", "subprocess with shell=True"),
    (_rx(r"\bpickle\.loads?\s*\("), Severity.MEDIUM, "deserialization", "Unsafe pickle deserialization"),
    (_rx(r"\byaml\.load\s*\((?!.*Loader)"), Severity.MEDIUM, "deserialization", "yaml.load without a safe Loader"),
    (_rx(r"\bDEBUG\s*=\s*True"), Severity.MEDIUM, "config", "DEBUG=True (must be False in production)"),
    (_rx(r"""ALLOWED_HOSTS\s*=\s*\[\s*['"]\*['"]"""), Severity.MEDIUM, "config", "ALLOWED_HOSTS=['*']"),
    (_rx(r"\bverify\s*=\s*False"), Severity.MEDIUM, "tls", "TLS verification disabled (verify=False)"),
    (_rx(r"""\.execute\s*\(\s*f['"]"""), Severity.MEDIUM, "sql-injection", "SQL built with an f-string"),
    (_rx(r"""\.execute\s*\([^)]*%\s*\("""), Severity.MEDIUM, "sql-injection", "SQL built with %-formatting"),
    (_rx(r"\bmark_safe\s*\("), Severity.LOW, "xss", "mark_safe() can introduce XSS"),
]

_JS_RULES = [
    (_rx(r"\beval\s*\("), Severity.HIGH, "code-injection", "Use of eval()"),
    (_rx(r"\b(?:child_process|exec|execSync)\b.*(?:`|\+)"), Severity.HIGH, "command-injection",
     "Shell command built from interpolation/concatenation"),
    (_rx(r"\.innerHTML\s*="), Severity.MEDIUM, "xss", "Assignment to innerHTML"),
    (_rx(r"dangerouslySetInnerHTML"), Severity.MEDIUM, "xss", "React dangerouslySetInnerHTML"),
    (_rx(r"\bdocument\.write\s*\("), Severity.MEDIUM, "xss", "document.write()"),
]

_GO_RULES = [
    (_rx(r'exec\.Command\s*\(\s*"(?:sh|bash)"\s*,\s*"-c"'), Severity.HIGH, "command-injection",
     "Shell -c command execution"),
]

_PY_EXT = (".py",)
_JS_EXT = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
_GO_EXT = (".go",)
# Files where a "secret" is expected to be a placeholder, not a real leak.
_SECRET_SKIP = (".env.example", ".env.sample", ".env.template")


def _rules_for(path: str):
    low = path.lower()
    rules = list(_COMMON_RULES)
    if low.endswith(_PY_EXT):
        rules += _PY_RULES
    elif low.endswith(_JS_EXT):
        rules += _JS_RULES
    elif low.endswith(_GO_EXT):
        rules += _GO_RULES
    return rules


def scan_files(files: dict[str, str]) -> list[Finding]:
    """Scan {path: content} and return findings, most severe first."""
    findings: list[Finding] = []
    for path, content in files.items():
        if not isinstance(content, str):
            continue
        name = PurePosixPath(path).name.lower()
        skip_secrets = name.endswith(_SECRET_SKIP) or name in _SECRET_SKIP
        rules = _rules_for(path)
        for lineno, line in enumerate(content.splitlines(), start=1):
            for rx, severity, category, message in rules:
                if category == "secret" and skip_secrets:
                    continue
                if rx.search(line):
                    findings.append(Finding(severity, category, message, path,
                                            lineno, line.strip()))
    findings.sort(key=lambda f: (_ORDER[f.severity], f.path, f.line))
    return findings


def summarize(findings: list[Finding]) -> dict:
    counts = {Severity.HIGH: 0, Severity.MEDIUM: 0, Severity.LOW: 0}
    for f in findings:
        counts[f.severity] += 1
    return {"total": len(findings), **counts}
