"""The initial agent catalog (docs/PRODUCT.md §2).

Each definition grants the minimum capabilities its role needs. Note what is
*absent*: no agent holds a SENSITIVE capability (production deploy, billing,
prod secrets) — those are approval-gated. The Frontend agent cannot touch the
backend or billing; the Database agent gets migrations but not production data
(there is no such capability to grant); DevOps deploys to dev/staging but not
production. Later specialist agents (Mobile, Security, …) register here too.
"""
from apps.agents.capabilities import Capability as C
from apps.agents.registry import AgentDefinition, AgentRegistry

registry = AgentRegistry()


def _reg(key, name, description, capabilities):
    return registry.register(
        AgentDefinition(key, name, description, frozenset(capabilities))
    )


LEAD = _reg(
    "lead",
    "Lead Agent",
    "Analyses the requirement, plans the task graph, and delegates to "
    "specialists through the Orchestrator. Coordinates; does not write code.",
    {
        C.ORCHESTRATE,
        C.READ_REQUIREMENTS,
        C.READ_ARCHITECTURE,
        C.READ_BACKEND,
        C.READ_FRONTEND,
        C.READ_DATABASE,
        C.READ_TESTS,
        C.READ_INFRASTRUCTURE,
    },
)

PRODUCT = _reg(
    "product",
    "Product Agent",
    "Turns a user's intent into a product definition and scope.",
    {C.READ_REQUIREMENTS, C.WRITE_REQUIREMENTS},
)

REQUIREMENTS = _reg(
    "requirements",
    "Requirements Agent",
    "Elicits and structures functional requirements and acceptance criteria.",
    {C.READ_REQUIREMENTS, C.WRITE_REQUIREMENTS},
)

ARCHITECT = _reg(
    "architect",
    "Architect Agent",
    "Designs the system architecture from the requirements.",
    {C.READ_REQUIREMENTS, C.READ_ARCHITECTURE, C.WRITE_ARCHITECTURE},
)

BACKEND = _reg(
    "backend",
    "Backend Agent",
    "Implements backend code and APIs against the architecture.",
    {
        C.READ_ARCHITECTURE,
        C.READ_BACKEND,
        C.WRITE_BACKEND,
        C.READ_DATABASE,
        C.RUN_TESTS,
    },
)

FRONTEND = _reg(
    "frontend",
    "Frontend Agent",
    "Implements the frontend. Cannot modify backend, billing, or production.",
    {C.READ_ARCHITECTURE, C.READ_FRONTEND, C.WRITE_FRONTEND, C.RUN_TESTS},
)

DATABASE = _reg(
    "database",
    "Database Agent",
    "Owns schema and migrations; optimises queries. Cannot modify prod data.",
    {C.READ_ARCHITECTURE, C.READ_DATABASE, C.WRITE_MIGRATIONS, C.RUN_TESTS},
)

TESTING = _reg(
    "testing",
    "Testing Agent",
    "Writes and runs tests across backend and frontend.",
    {C.READ_BACKEND, C.READ_FRONTEND, C.READ_TESTS, C.WRITE_TESTS, C.RUN_TESTS},
)

CODE_REVIEW = _reg(
    "code_review",
    "Code Review Agent",
    "Reviews changes for correctness, security, and maintainability.",
    {C.READ_BACKEND, C.READ_FRONTEND, C.READ_TESTS, C.REVIEW_CODE},
)

DEVOPS = _reg(
    "devops",
    "DevOps Agent",
    "Builds and deploys to dev and staging. Production deploys need approval.",
    {C.READ_INFRASTRUCTURE, C.DEPLOY_DEV, C.DEPLOY_STAGING},
)
