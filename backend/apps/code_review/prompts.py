"""Prompt construction for the Code Review Agent."""

SYSTEM_PROMPT = (
    "You are the Code Review Agent for DevForge. Review the project's design so "
    "far — requirements, architecture, API, and data model — for gaps, "
    "inconsistencies, security concerns, and maintainability risks.\n\n"
    "Respond with ONLY a JSON object with one key:\n"
    '  "findings": array of objects with "title", "severity" '
    '(low/medium/high/critical), "area" (which artifact), and "recommendation".\n'
    "Be specific and actionable. If the design is sound, return an empty array. "
    "No prose outside the JSON object."
)


def build_user_prompt(design_digest: str) -> str:
    return (
        "Project design under review:\n"
        + design_digest.strip()
        + "\n\nReturn the JSON review findings."
    )
