"""Prompt construction for the Frontend Agent."""


def system_prompt(stack=None) -> str:
    """Design + (for a runnable frontend stack) implement the app.

    Without a runnable stack the agent stays design-only (screens). With one, it
    also emits real source and a framework-free, node-testable logic layer.
    """
    base = [
        "You are the Frontend Agent for DevForge. Given a project's requirements, "
        "architecture, and API, design the application's screens for the chosen "
        "frontend framework.",
        "",
        "Respond with ONLY a JSON object. It MUST include:",
        '  "screens": array of {"name","purpose","route","components" (UI element '
        'names),"data_needs" (API endpoints/data the screen consumes)}.',
    ]
    if stack is not None:
        base += [
            '  "files": array of {"path","content"} — the actual source.',
            "",
            "Source requirements:",
            stack.prompt_hint,
        ]
    base += ["", "Cover the user journeys implied by the requirements. No prose "
             "outside the JSON."]
    return "\n".join(base)


# Back-compat: the plain design-only system prompt.
SYSTEM_PROMPT = system_prompt(None)


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
