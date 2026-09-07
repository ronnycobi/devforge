"""Prompt construction for the Backend Agent (stack-driven).

The system prompt is assembled from a stack-agnostic base plus the chosen stack's
own guidance (Stack.prompt_hint), so the same agent generates Django, a stdlib
project, or any future stack without special-casing.
"""


def system_prompt(stack) -> str:
    base = [
        "You are the Backend Agent for DevForge. Implement the backend for this "
        f"project in the chosen stack: {stack.framework or stack.language}.",
        "",
        "Respond with ONLY a JSON object. It MUST include:",
        '  "files": array of {"path","content"} — the source files,',
        '  "endpoints": array of {"method","path","purpose","module","auth"} '
        "describing the HTTP API.",
    ]
    if stack.needs_app_label:
        base.append('  "app_label": a short snake_case app name.')
    base.append("")
    base.append("Stack-specific requirements:")
    base.append(stack.prompt_hint)
    base.append("")
    base.append("Keep it small, coherent, and passing. No prose outside the JSON.")
    return "\n".join(base)


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
    parts.append("Return the JSON with the backend files and the API they expose.")
    return "\n\n".join(parts)
