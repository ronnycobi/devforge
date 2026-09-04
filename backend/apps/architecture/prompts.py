"""Prompt construction for the Architect Agent."""

SYSTEM_PROMPT = (
    "You are the Architect Agent for DevForge. Given a project's functional "
    "requirements, design a pragmatic system architecture — a modular monolith "
    "unless the requirements clearly demand otherwise.\n\n"
    "Respond with ONLY a JSON object with two keys:\n"
    '  "components": array of objects with "name", "responsibility", '
    '"technology", and "depends_on" (array of other component names),\n'
    '  "tech_decisions": array of objects with "title", "choice", and '
    '"rationale".\n'
    "Keep it simple and buildable. No prose outside the JSON object."
)


def build_user_prompt(requirements_digest: str, existing_architecture: str = "",
                      brief: str = "") -> str:
    parts = []
    if brief.strip():
        parts.append("Product brief:\n" + brief.strip())
    if requirements_digest.strip():
        parts.append("Requirements:\n" + requirements_digest.strip())
    if existing_architecture.strip():
        parts.append(
            "Existing architecture (refine rather than duplicate):\n"
            + existing_architecture.strip()
        )
    parts.append("Return the JSON architecture for this project.")
    return "\n\n".join(parts)
