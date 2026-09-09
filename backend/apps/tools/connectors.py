"""Connectors — DevForge's MCP-style layer for reaching external systems.

A Connector is a Tool (so it registers in the same Tool Registry and is enforced by
the same Toolbelt — one permission choke point), plus two extra rules that matter for
anything touching outside systems:

  1. Credential-safe: a connector reads its secret from the ENVIRONMENT only. The
     secret is never stored, never returned to the agent, and never appears in
     describe()/status — the agent is granted the *ability to invoke*, not the key
     (mirrors the store/signing credential rule).
  2. Honest availability: a connector is inert until configured. Without its
     credential it refuses (ToolResult.failed) rather than fake a call, and even with
     a credential present it refuses until a real, doc-verified integration is wired —
     never a fabricated response (same posture as the payment gateways).

Concrete connectors here (GitHub, Slack, external Postgres) are the gated seams; the
live API code is added per connector once its SDK + credentials exist, behind
is_configured(). All require the USE_CONNECTORS capability.
"""
from __future__ import annotations

import os

from apps.agents.capabilities import Capability
from apps.tools.base import Tool, ToolResult
from apps.tools.registry import registry


class Connector(Tool):
    key: str = ""
    provider: str = ""
    env_var: str = ""                       # credential source — ENV only
    required = frozenset({Capability.USE_CONNECTORS})

    def is_configured(self) -> bool:
        return bool(self.env_var and os.environ.get(self.env_var))

    def _run(self, project, action: str, **kwargs) -> ToolResult:
        if not self.is_configured():
            return ToolResult.failed(
                f"{self.provider} connector is not configured "
                f"({self.env_var} is not set) — it will not run until connected."
            )
        return self._call(project, action, **kwargs)

    def _call(self, project, action: str, **kwargs) -> ToolResult:
        # A credential is present, but the live API integration for this connector is
        # not enabled in this build yet. Refuse rather than fabricate a response.
        return ToolResult.failed(
            f"{self.provider} credentials are present, but its live integration is not "
            f"enabled yet. Complete the {self.provider} connector before using it."
        )

    def describe(self) -> dict:
        d = super().describe()
        d.update({"provider": self.provider, "configured": self.is_configured(),
                  "credential_env": self.env_var})   # the VAR NAME, never its value
        return d


class GitHubConnector(Connector):
    name = "connector.github"
    key = "github"
    provider = "GitHub"
    description = "Read repositories and manage issues/PRs on GitHub."
    env_var = "GITHUB_TOKEN"
    actions = frozenset({"repo.info", "issues.list", "issues.create"})


class SlackConnector(Connector):
    name = "connector.slack"
    key = "slack"
    provider = "Slack"
    description = "Post notifications and messages to Slack."
    env_var = "SLACK_BOT_TOKEN"
    actions = frozenset({"message.send"})


class PostgresConnector(Connector):
    name = "connector.postgres"
    key = "postgres"
    provider = "External Postgres"
    description = "Run read queries against a connected external Postgres database."
    env_var = "CONNECTOR_POSTGRES_URL"
    actions = frozenset({"query"})


_CONNECTORS = [GitHubConnector(), SlackConnector(), PostgresConnector()]

for _c in _CONNECTORS:
    if _c.name not in registry:
        registry.register(_c)


def all_connectors() -> list[Connector]:
    return [t for t in registry.all() if isinstance(t, Connector)]


def connector_status() -> list[dict]:
    """Honest inventory for the admin: which connectors exist and whether each is
    configured — never the credential value."""
    return [
        {"key": c.key, "provider": c.provider, "configured": c.is_configured(),
         "credential_env": c.env_var, "actions": sorted(c.actions)}
        for c in all_connectors()
    ]
