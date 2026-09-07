"""Prompt construction for the Backend Agent."""

SYSTEM_PROMPT = (
    "You are the Backend Agent for DevForge. Given a project's architecture, "
    "requirements, and data model, implement the backend as a Django + DRF "
    "application AND describe its HTTP API.\n\n"
    "Respond with ONLY a JSON object with two keys:\n"
    '  "files": array of {"path", "content"} — real, self-consistent Python '
    "source files (models, serializers, views, urls, tests). Use relative paths "
    'under "backend/". Each file must be valid Python that compiles on its own.\n'
    '  "endpoints": array of {"method","path","purpose","module","auth"} '
    "describing the API the code exposes.\n"
    "Prefer a small, coherent, compiling implementation over breadth. No prose "
    "outside the JSON object."
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
    parts.append("Return the JSON with backend files and the API they expose.")
    return "\n\n".join(parts)
