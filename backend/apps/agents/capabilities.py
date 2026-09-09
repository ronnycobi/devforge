"""Agent capabilities — the least-privilege permission vocabulary.

Each agent declares exactly the capabilities it needs and nothing more (see
docs/PRODUCT.md §2). Tools and the Orchestrator check these before performing a
sensitive action, so the set an agent holds is the hard boundary on what it can
do. Capabilities in SENSITIVE must never be granted to an automated agent by
default — they gate human-approval paths (production deploys, billing, prod
secrets).
"""
from enum import StrEnum


class Capability(StrEnum):
    # Coordination
    ORCHESTRATE = "orchestrate"

    # Requirements / product
    READ_REQUIREMENTS = "read_requirements"
    WRITE_REQUIREMENTS = "write_requirements"

    # Architecture
    READ_ARCHITECTURE = "read_architecture"
    WRITE_ARCHITECTURE = "write_architecture"

    # Backend code
    READ_BACKEND = "read_backend"
    WRITE_BACKEND = "write_backend"

    # Frontend code
    READ_FRONTEND = "read_frontend"
    WRITE_FRONTEND = "write_frontend"

    # Database
    READ_DATABASE = "read_database"
    WRITE_MIGRATIONS = "write_migrations"

    # Testing
    READ_TESTS = "read_tests"
    WRITE_TESTS = "write_tests"
    RUN_TESTS = "run_tests"

    # Review
    REVIEW_CODE = "review_code"

    # Tools — least-privilege access to the Tool Registry (apps.tools)
    USE_REPOSITORY = "use_repository"      # read files / search / diff / log
    WRITE_REPOSITORY = "write_repository"  # write files / commit / branch
    USE_SANDBOX = "use_sandbox"            # execute code in the isolated sandbox
    USE_CONNECTORS = "use_connectors"      # call external systems via a Connector

    # Infrastructure / deployment
    READ_INFRASTRUCTURE = "read_infrastructure"
    DEPLOY_DEV = "deploy_dev"
    DEPLOY_STAGING = "deploy_staging"
    DEPLOY_PRODUCTION = "deploy_production"

    # Sensitive — approval-gated, never default
    MANAGE_BILLING = "manage_billing"
    ACCESS_PRODUCTION_SECRETS = "access_production_secrets"


# Capabilities that require an explicit human-approval path; no default agent
# in the catalog may hold any of these.
SENSITIVE = frozenset(
    {
        Capability.DEPLOY_PRODUCTION,
        Capability.MANAGE_BILLING,
        Capability.ACCESS_PRODUCTION_SECRETS,
    }
)
