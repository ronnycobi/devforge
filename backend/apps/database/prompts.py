"""Prompt construction for the Database Agent."""

SYSTEM_PROMPT = (
    "You are the Database Agent for DevForge. Given a project's architecture, "
    "requirements, and API, design the relational data model (PostgreSQL).\n\n"
    "Respond with ONLY a JSON object with one key:\n"
    '  "models": array of objects with "name", "description", "fields" (array of '
    '{"name","type","nullable","note"}), and "relations" (array of strings like '
    '"belongs_to Organization").\n'
    "Design normalized tables that satisfy the requirements. No prose outside the JSON."
)


def build_user_prompt(architecture_digest, requirements_digest, api_digest,
                      existing_schema="", brief=""):
    parts = []
    if brief.strip():
        parts.append("Product brief:\n" + brief.strip())
    if architecture_digest.strip():
        parts.append("Architecture:\n" + architecture_digest.strip())
    if requirements_digest.strip():
        parts.append("Requirements:\n" + requirements_digest.strip())
    if api_digest.strip():
        parts.append("API:\n" + api_digest.strip())
    if existing_schema.strip():
        parts.append("Existing schema (refine, don't duplicate):\n" + existing_schema.strip())
    parts.append("Return the JSON data model for this project.")
    return "\n\n".join(parts)
