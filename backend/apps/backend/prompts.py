"""Prompt construction for the Backend Agent."""

SYSTEM_PROMPT = (
    "You are the Backend Agent for DevForge. Given a project's architecture, "
    "requirements, and data model, implement a COMPLETE, SELF-CONTAINED, RUNNABLE "
    "Python project that realizes the core domain logic AND its HTTP API surface.\n\n"
    "Hard constraints (the project runs in an isolated sandbox with NO network and "
    "NO installed third-party packages):\n"
    "- Use ONLY the Python standard library. No Django, Flask, requests, pytest, etc.\n"
    "- Flat layout: modules and test files live at the repository root.\n"
    "- Include unittest tests in files named test_*.py that exercise the domain "
    "logic. The whole thing must pass `python -m unittest discover`.\n\n"
    "Respond with ONLY a JSON object with two keys:\n"
    '  "files": array of {"path","content"} — the complete project (domain '
    "modules + test_*.py), each a valid, importable Python file.\n"
    '  "endpoints": array of {"method","path","purpose","module","auth"} '
    "describing the HTTP API the domain logic is meant to expose.\n"
    "Prefer a small, coherent, passing project over breadth. No prose outside the JSON."
)


def build_user_prompt(architecture_digest, requirements_digest, schema_digest,
                      existing_api="", brief=""):
    parts = []
    if brief.strip():
        parts.append("Product brief:\n" + brief.strip())
    if architecture_digest.strip():
        parts.append("Architecture:\n" + architecture_digest.strip())
    if requirements_digest.strip():
        parts.append("Requirements:\n" + requirements_digest.strip())
    if schema_digest.strip():
        parts.append("Data model:\n" + schema_digest.strip())
    if existing_api.strip():
        parts.append("Existing API (refine, don't duplicate):\n" + existing_api.strip())
    parts.append(
        "Return the JSON with a complete runnable stdlib-only project (with "
        "unittest tests) and the API it exposes."
    )
    return "\n\n".join(parts)
