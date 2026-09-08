"""Database capability registry — technology-agnostic, extensible.

DevForge must not assume PostgreSQL, SQL, or a relational model. Each database is
described by what it *can actually do* (a capability profile), keyed by the same
ids as the Technology Registry. Agents reason from capabilities rather than
hard-coding one engine's behaviour: e.g. only emit foreign keys / migrations for a
database that supports them, and treat a document or key-value store on its own
terms.

Adding a database = adding one DatabaseProfile here. Capabilities are declarative
data (no drivers), so this is safe and complete offline. A *live* provider (real
connections, inspection) is a separate, incremental concern — see providers.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Category(str, Enum):
    RELATIONAL = "relational"
    DISTRIBUTED_SQL = "distributed_sql"
    DOCUMENT = "document"
    KEY_VALUE = "key_value"
    WIDE_COLUMN = "wide_column"
    SEARCH = "search"
    GRAPH = "graph"


# The capability flags a profile can declare. Anything absent defaults to False.
CAPABILITIES = (
    "sql",
    "transactions",
    "foreign_keys",
    "joins",
    "fixed_schema",
    "migrations",
    "json",
    "full_text_search",
    "vector",
    "replication",
)


@dataclass(frozen=True)
class DatabaseProfile:
    id: str
    name: str
    category: Category
    sql: bool = False
    transactions: bool = False
    foreign_keys: bool = False
    joins: bool = False
    fixed_schema: bool = False
    migrations: bool = False
    json: bool = False
    full_text_search: bool = False
    vector: bool = False
    replication: bool = False
    # Whether DevForge has a live provider (real connect/inspect) for it yet.
    has_provider: bool = False

    def supports(self, capability: str) -> bool:
        if capability not in CAPABILITIES:
            raise ValueError(f"Unknown capability '{capability}'")
        return bool(getattr(self, capability))

    def as_dict(self) -> dict:
        d = {"id": self.id, "name": self.name, "category": self.category.value,
             "has_provider": self.has_provider}
        d.update({c: getattr(self, c) for c in CAPABILITIES})
        return d


# --- the registry -----------------------------------------------------------
# Initial databases are described fully; a few others are registered as category
# descriptors to prove the abstraction is extensible (providers added later).
_REGISTRY: dict[str, DatabaseProfile] = {
    p.id: p
    for p in [
        DatabaseProfile(
            "postgresql", "PostgreSQL", Category.RELATIONAL, sql=True, transactions=True,
            foreign_keys=True, joins=True, fixed_schema=True, migrations=True, json=True,
            full_text_search=True, vector=True, replication=True, has_provider=False,
        ),
        DatabaseProfile(
            "mysql", "MySQL", Category.RELATIONAL, sql=True, transactions=True,
            foreign_keys=True, joins=True, fixed_schema=True, migrations=True, json=True,
            full_text_search=True, replication=True,
        ),
        DatabaseProfile(
            "mariadb", "MariaDB", Category.RELATIONAL, sql=True, transactions=True,
            foreign_keys=True, joins=True, fixed_schema=True, migrations=True, json=True,
            full_text_search=True, replication=True,
        ),
        DatabaseProfile(
            "sqlite", "SQLite", Category.RELATIONAL, sql=True, transactions=True,
            foreign_keys=True, joins=True, fixed_schema=True, migrations=True, json=True,
            full_text_search=True, has_provider=True,  # implemented via stdlib sqlite3
        ),
        DatabaseProfile(
            "mongodb", "MongoDB", Category.DOCUMENT, sql=False, transactions=True,
            foreign_keys=False, joins=False, fixed_schema=False, migrations=False,
            json=True, full_text_search=True, vector=True, replication=True,
        ),
        DatabaseProfile(
            "redis", "Redis", Category.KEY_VALUE, sql=False, transactions=False,
            foreign_keys=False, joins=False, fixed_schema=False, migrations=False,
            replication=True,
        ),
        # Extensibility descriptors (planned providers) — other categories present.
        DatabaseProfile(
            "cockroachdb", "CockroachDB", Category.DISTRIBUTED_SQL, sql=True,
            transactions=True, foreign_keys=True, joins=True, fixed_schema=True,
            migrations=True, json=True, replication=True,
        ),
        DatabaseProfile(
            "elasticsearch", "Elasticsearch", Category.SEARCH, full_text_search=True,
            json=True, vector=True, replication=True,
        ),
        DatabaseProfile("neo4j", "Neo4j", Category.GRAPH, transactions=True, replication=True),
    ]
}


def get_database(database_id: str) -> DatabaseProfile | None:
    return _REGISTRY.get(database_id)


def all_databases() -> list[DatabaseProfile]:
    return list(_REGISTRY.values())


def databases_by_category(category: Category) -> list[DatabaseProfile]:
    return [p for p in _REGISTRY.values() if p.category == category]
