"""Database provider abstraction (technology-agnostic).

A DatabaseProvider is a thin, capability-gated adapter over one database engine:
connect, inspect the live schema, run a query, health-check. Operations that the
engine doesn't support raise UnsupportedOperation rather than pretending — the
caller checks `provider.supports(...)` first.

Only SQLite has a real provider today (stdlib sqlite3 — no server, works offline),
which is enough to exercise the whole abstraction end to end. Providers for other
engines are added incrementally, one adapter at a time, without changing callers
or the Database Agent. Unimplemented engines fail honestly via get_provider().
"""
from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod

from apps.database.capabilities import DatabaseProfile, get_database


class UnsupportedOperation(Exception):
    """Raised when a capability the engine lacks is requested."""


class ProviderUnavailable(Exception):
    """Raised when no live provider is implemented for a database yet."""


class DatabaseProvider(ABC):
    """Common interface. Concrete providers implement connect/inspect/query."""

    profile: DatabaseProfile

    def capabilities(self) -> DatabaseProfile:
        return self.profile

    def supports(self, capability: str) -> bool:
        return self.profile.supports(capability)

    def _require(self, capability: str) -> None:
        if not self.supports(capability):
            raise UnsupportedOperation(
                f"{self.profile.name} does not support '{capability}'."
            )

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def health_check(self) -> dict: ...

    @abstractmethod
    def inspect_schema(self) -> dict:
        """Return {tables: {name: {columns:[...], primary_key:[...]}}} (or the
        engine's equivalent). Read-only."""

    @abstractmethod
    def execute_query(self, query, params=()) -> list: ...


class SQLiteProvider(DatabaseProvider):
    """Real provider over stdlib sqlite3 (file path or ':memory:')."""

    def __init__(self, path: str = ":memory:"):
        self.profile = get_database("sqlite")
        self.path = path
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        if self._conn is None:
            self._conn = sqlite3.connect(self.path)
            self._conn.row_factory = sqlite3.Row

    def disconnect(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _cx(self) -> sqlite3.Connection:
        self.connect()
        return self._conn

    def health_check(self) -> dict:
        try:
            self._cx().execute("SELECT 1")
            return {"ok": True, "database": self.profile.id, "version": sqlite3.sqlite_version}
        except sqlite3.Error as exc:
            return {"ok": False, "database": self.profile.id, "error": str(exc)}

    def inspect_schema(self) -> dict:
        cx = self._cx()
        tables: dict[str, dict] = {}
        names = [
            r["name"]
            for r in cx.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        for name in names:
            cols, pk = [], []
            for col in cx.execute(f"PRAGMA table_info('{name}')"):
                cols.append({"name": col["name"], "type": col["type"],
                             "nullable": not col["notnull"]})
                if col["pk"]:
                    pk.append(col["name"])
            tables[name] = {"columns": cols, "primary_key": pk}
        return {"database": self.profile.id, "tables": tables}

    def execute_query(self, query, params=()) -> list:
        cur = self._cx().execute(query, params)
        if cur.description is None:  # non-SELECT
            self._conn.commit()
            return []
        return [dict(r) for r in cur.fetchall()]


# Registered live providers. Add an entry when an adapter is implemented.
_PROVIDERS = {"sqlite": SQLiteProvider}


def get_provider(database_id: str, **kwargs) -> DatabaseProvider:
    """Return a live provider for `database_id`, or fail honestly if none exists."""
    if get_database(database_id) is None:
        raise ProviderUnavailable(f"Unknown database '{database_id}'.")
    factory = _PROVIDERS.get(database_id)
    if factory is None:
        raise ProviderUnavailable(
            f"No live provider is implemented for '{database_id}' yet "
            "(capabilities are known; the adapter is planned)."
        )
    return factory(**kwargs)


def has_provider(database_id: str) -> bool:
    return database_id in _PROVIDERS
