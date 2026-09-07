"""Prompt construction for the Frontend Agent."""

SYSTEM_PROMPT = (
    "You are the Frontend Agent for DevForge. Given a project's requirements, "
    "architecture, and API, design the screens of the application for the chosen "
    "frontend framework.\n\n"
    "Respond with ONLY a JSON object with one key:\n"
    '  "screens": array of objects with "name", "purpose", "route", '
    '"components" (array of UI element names), and "data_needs" (array of API '
    "endpoints or data this screen consumes).\n"
    "Cover the user journeys implied by the requirements. No prose outside the JSON."
)


def build_user_prompt(requirements_digest, api_digest, existing_screens="", brief="",
                      framework=""):
    parts = []
    if framework:
        parts.append(f"Target frontend framework: {framework}.")
    if brief.strip():
        parts.append("Product brief:\n" + brief.strip())
    if requirements_digest.strip():
        parts.append("Requirements:\n" + requirements_digest.strip())
    if api_digest.strip():
        parts.append("Available API:\n" + api_digest.strip())
    if existing_screens.strip():
        parts.append("Existing screens (refine, don't duplicate):\n" + existing_screens.strip())
    parts.append("Return the JSON screen design for this project.")
    return "\n\n".join(parts)
