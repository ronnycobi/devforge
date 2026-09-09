# DevForge product capability: Connectors, Skills, Hooks (phased plan)

Separate from the repo tooling in `.claude/` (which helps *build* DevForge), this is
about DevForge the **product** offering the same three ideas to its customers — so a
DevForge-generated app and its agents can connect to external systems, follow saved
playbooks, and run guardrails. Not built yet; this is the plan.

The seed already exists: **`apps/tools`** (the Tool Registry + Toolbelt) is DevForge's
capability-gated agent-tool system — the natural foundation for "connectors."

## 1. Connectors (DevForge's MCP layer)
Let product agents (and generated apps) use external systems through a permissioned,
provider-agnostic layer — the same honesty rules as everything else: a connector is
inert until real credentials exist, and never fakes a call.

- Extend `apps/tools` with a `Connector` abstraction alongside the built-in tools.
- Each connector declares required capabilities/scopes; the Toolbelt stays the single
  permission choke point. Secrets are environment/vault-only, never handed to an agent
  (mirrors the store/signing credential rule).
- MCP interop: adopt the Model Context Protocol so third-party MCP servers can be
  registered as connectors without bespoke code.
- Start with connectors we can genuinely run and test; everything else reports
  "not configured" and refuses.

## 2. Skills library (reusable playbooks)
Curated, versioned instructions the Lead Agent loads for a task ("build a CRM",
"add Stripe checkout", house content style).

- New app (e.g. `apps/skills`): `Skill` = name, description, trigger keywords, body,
  scope (global / org / project), enabled flag.
- The orchestrator selects relevant skills by the brief and injects them as guidance —
  the same way `store_provision` is triggered when the brief implies a store.
- Org-authored skills let a customer encode "how we build things here."

## 3. Generation hooks (guardrails on the build)
Deterministic checks that fire at points in the generate → test → deploy pipeline —
the platform version of the repo hook above.

- Model: `Hook` = event (pre_change / post_build / pre_deploy / post_deploy),
  action (run tests, security scan, lint, block on policy), scope, enabled.
- Wire into the existing change-request + orchestrator flow; a failing blocking hook
  stops promotion (already the posture: branch → tests → security → review → deploy).
- Reuse existing machinery: the security scanner, the test runner, the readiness
  engines — hooks orchestrate them, they don't reinvent them.

## Sequencing
1. Connectors on top of `apps/tools` (highest leverage; the registry exists).
2. Skills library (turns one-off provisioning like `store_provision` into a general
   mechanism).
3. Generation hooks (formalize the guardrails already present in the change loop).

Each ships behind the platform's standing rules: capability-gated, credential-safe,
and never faking a capability that isn't really there.
