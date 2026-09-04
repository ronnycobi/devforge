"""Prompt construction for the Backend Agent."""

SYSTEM_PROMPT = (
    "You are the Backend Agent for DevForge. Given a project's architecture and "
    "requirements, design the backend HTTP API — the endpoints needed to satisfy "
    "the requirements, grouped by module.\n\n"
    "Respond with ONLY a JSON object with one key:\n"
    '  "endpoints": array of objects with "method" (GET/POST/...), "path", '
    '"purpose", "module", "auth" (e.g. "required"/"public"), "request" (object '
    'describing the body/params), and "response" (object describing the result).\n'
    "Design a REST API against the architecture. No prose outside the JSON object."
)


def build_user_prompt(architecture_digest: str, requirements_digest: str,
                      existing_api: str = "", brief: str = "") -> str:
    parts = []
    if brief.strip():
        parts.append("Product brief:\n" + brief.strip())
    if architecture_digest.strip():
        parts.append("Architecture:\n" + architecture_digest.strip())
    if requirements_digest.strip():
        parts.append("Requirements:\n" + requirements_digest.strip())
    if existing_api.strip():
        parts.append("Existing API (refine, don't duplicate):\n" + existing_api.strip())
    parts.append("Return the JSON API design for this project.")
    return "\n\n".join(parts)
