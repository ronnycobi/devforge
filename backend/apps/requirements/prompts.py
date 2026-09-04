"""Prompt construction for the Requirements Agent.

Kept separate from the agent so the wording can evolve without touching control
flow. The model is asked for a strict JSON array; the agent parses defensively
(models don't always comply, and the offline stub never will).
"""

SYSTEM_PROMPT = (
    "You are the Requirements Agent for DevForge, an AI software-engineering "
    "platform. Given a short product brief, produce clear, testable functional "
    "requirements.\n\n"
    "Respond with ONLY a JSON array. Each element is an object with:\n"
    '  "title": a short imperative requirement name,\n'
    '  "description": one or two sentences of detail,\n'
    '  "acceptance_criteria": an array of concrete, checkable strings.\n'
    "Do not include any prose outside the JSON array."
)


def build_user_prompt(brief: str, existing_context: str = "") -> str:
    parts = []
    if existing_context.strip():
        parts.append(
            "Existing project context (do not duplicate what is already covered):\n"
            + existing_context.strip()
        )
    parts.append("Product brief:\n" + brief.strip())
    parts.append(
        "Return the JSON array of functional requirements for this brief."
    )
    return "\n\n".join(parts)
