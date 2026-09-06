"""Per-agent estimation defaults.

Rough token budgets and complexity per specialist, used only for cost estimation.
These are deliberately coarse — the estimator turns them into ranges, and real
usage is measured and billed separately by apps.credits.
"""
from apps.model_router.router import TaskComplexity

DEFAULT_PIPELINE = [
    "requirements",
    "architect",
    "backend",
    "frontend",
    "database",
    "testing",
    "code_review",
]

AGENT_COMPLEXITY = {
    "requirements": TaskComplexity.MEDIUM,
    "architect": TaskComplexity.HIGH,
    "backend": TaskComplexity.HIGH,
    "frontend": TaskComplexity.MEDIUM,
    "database": TaskComplexity.HIGH,
    "testing": TaskComplexity.MEDIUM,
    "code_review": TaskComplexity.HIGH,
}

# Approx total (input + output) tokens a single run of each agent consumes.
AGENT_TOKEN_ESTIMATE = {
    "requirements": 3000,
    "architect": 5000,
    "backend": 6000,
    "frontend": 4000,
    "database": 5000,
    "testing": 4000,
    "code_review": 4000,
}
