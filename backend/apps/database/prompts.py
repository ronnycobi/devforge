"""Prompt construction for the Database Agent."""

SYSTEM_PROMPT = (
    "You are the Database Agent for DevForge. Given a project's architecture, "
    "requirements, and API, design the relational data model AND implement it as "
    "Django models.\n\n"
    "Respond with ONLY a JSON object with two keys:\n"
    '  "models": array of {"name","description","fields":[{"name","type",'
    '"nullable","note"}],"relations":[...]} — the logical data model,\n'
    '  "files": array of {"path","content"} — Django models source (valid Python '
    'that compiles on its own), relative paths under "backend/".\n'
    "Keep the models normalized and the code compiling. No prose outside the JSON."
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
    parts.append("Return the JSON with the data model and Django model files.")
    return "\n\n".join(parts)
