"""Prompt construction for the Testing Agent."""

SYSTEM_PROMPT = (
    "You are the Testing Agent for DevForge. Given a project's requirements and "
    "API, design the test cases that verify the system meets its requirements.\n\n"
    "Respond with ONLY a JSON object with one key:\n"
    '  "test_cases": array of objects with "title", "kind" '
    '(unit/integration/e2e/acceptance), "target" (what it exercises), "steps" '
    '(array of actions), and "expected" (the expected outcome).\n'
    "Cover the acceptance criteria of each requirement. No prose outside the JSON."
)


def build_user_prompt(requirements_digest, api_digest, existing_tests="", brief=""):
    parts = []
    if brief.strip():
        parts.append("Product brief:\n" + brief.strip())
    if requirements_digest.strip():
        parts.append("Requirements:\n" + requirements_digest.strip())
    if api_digest.strip():
        parts.append("API:\n" + api_digest.strip())
    if existing_tests.strip():
        parts.append("Existing tests (refine, don't duplicate):\n" + existing_tests.strip())
    parts.append("Return the JSON test plan for this project.")
    return "\n\n".join(parts)
