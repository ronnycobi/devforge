# DevForge — Product Definition & Roadmap

This is the *what* and the *when*. The *how you work in this repo* is in
[`../CLAUDE.md`](../CLAUDE.md). This document is a reference: read the parts a
task needs. It describes the destination; **it is not a mandate to build the
whole thing at once.**

---

## 1. What DevForge is

An AI software-engineering platform. Users describe software; specialized AI
agents build, test, review, deploy, and operate it. It is an **engineering
platform**, not a chatbot that generates code.

Users can: build websites, web apps, SaaS, APIs, and mobile apps; import,
analyze, improve, rebuild, and modernize existing/legacy software; deploy,
monitor, and maintain applications; export full source; deploy to their own
infrastructure or DevForge Cloud; and use multiple AI models and agents.

Product lifecycle: `BUILD → UNDERSTAND → IMPROVE → TEST → DEPLOY → OPERATE → MODERNIZE`.

## 2. Central runtime shape

```
USER → LEAD AGENT → AGENT ORCHESTRATOR → SPECIALIZED AGENTS → CONTROLLED TOOLS
     → CODE / INFRASTRUCTURE → TESTING → REVIEW → DEPLOYMENT
```

The Lead Agent coordinates. Specialists own specific responsibilities. The
Orchestrator owns communication, state, permissions, and execution. **Never a
single giant agent/prompt.**

### Agents

- **Initial:** Lead, Product, Requirements, Architect, Backend, Frontend,
  Database, Testing, Code Review, DevOps.
- **Later:** Mobile, Security, Commerce, Payment, Tax, Cloud, Monitoring,
  Scaling, Legacy Analysis, Migration.

Agents do not call each other directly — they go through the Orchestrator:
`Agent → Orchestrator → Task → Assigned Agent`. Each agent runs with **least
privilege** (e.g. the Frontend Agent cannot touch billing or production; the
Database Agent cannot mutate production data; deploys to production require
approval).

### Agent Orchestrator

Creates/assigns/tracks tasks; manages dependencies, execution, retries,
failures, approvals; tracks usage/cost; records decisions; maintains project
context. Execution must be **resumable** — a server restart must not lose task
state.

### Agent task model

Fields: `task_id, project_id, agent_id, parent_task_id, status, priority, input,
output, created_at, started_at, completed_at, model, tokens, credits, cost,
approval_required`.

States: `QUEUED, PLANNING, RUNNING, WAITING_FOR_TOOL, WAITING_FOR_AGENT,
WAITING_FOR_APPROVAL, COMPLETED, FAILED, CANCELLED, TIMEOUT, BLOCKED`.

## 3. Core subsystems (reference)

- **AI provider abstraction** — providers (Claude, OpenAI, Gemini, …) are
  replaceable behind one interface. Nothing depends on provider specifics.
  `App → Model Router → AIProvider → Provider → Model`.
- **Model Router** — picks a model by task type, complexity, context size,
  reasoning/quality/latency needs, customer preference, budget, availability.
  Optimizes quality + cost + speed + reliability. Never "most expensive by
  default."
- **Project intelligence** — persistent, structured per-project knowledge
  (requirements, architecture, business rules, tech decisions, schema, APIs,
  dependencies, known issues, agent decisions, deployment/infra, testing,
  security). Agents retrieve relevant context instead of re-sending the whole
  repo — for cost, consistency, and long-running projects.
- **Project digital twin** — a structured model of the built application
  (frontend/backend/db/APIs/auth/payments/jobs/external services/infra/
  monitoring), updated on change; eventually answers "if I change X, what's
  affected?"
- **Build sandbox** — isolated execution with CPU/memory/timeout/network/
  filesystem/process limits; destroyed after use.
- **Cost & credit engine** — track AI/model/token/compute/storage/bandwidth/db/
  build/deploy/monitoring, attributable to org/project/agent/task/provider/model.
  Customers get **DevForge credits** (an abstraction over tokens; plans and
  values are config, never hard-coded). **Budget protection:** per-month/project/
  infra caps; on exhaustion, **stop** and offer wait / buy / upgrade / reduce
  scope — never silent charges. A project cost analyzer gives **ranges** and
  requests approval before expensive work.
- **Cloud abstraction** — one `CloudProvider` interface over AWS/Azure/GCP/
  DigitalOcean/Kubernetes/DevForge Cloud. **DevForge Cloud** is a simple managed
  deployment experience (compute/db/storage/bandwidth/backups) — not an attempt
  to become AWS in v1.
- **Export & portability** — every project exports full source + tests +
  migrations + Docker/infra config + env template + docs + API spec + deploy
  config, independently runnable. Customers may deploy to their own infra or
  leave entirely. **No artificial lock-in** — customers stay because DevForge is
  useful.
- **Operations & scaling** — post-deploy monitoring (CPU/mem/db/latency/errors/
  traffic/storage/availability/security); ops agents detect → analyze →
  recommend → fix → test → PR → approval → deploy. No autonomous destructive
  production actions by default. Scaling intelligence forecasts future needs and
  recommends before acting.
- **Commerce & internationalization** — generated software supports products/
  cart/checkout/orders/payments/refunds/tax, and currency/language/timezone/VAT/
  date-number-address formats. Payment gateways are abstracted; customer payment
  credentials belong to the customer. Do not assume any single locale.
- **Enterprise** — SSO/SAML/OIDC/RBAC/SCIM, audit logs, private networking,
  encryption, customer-managed keys, data residency, private deployment/models,
  IP restrictions, approval policies. Don't expose enterprise source to external
  AI providers unnecessarily.
- **Audit & observability** — record important operations (user/agent/task/tool/
  repo change/model/usage/cost/approval/deploy/infra/security). DevForge itself
  must be observable (agent success/failure rates, task duration, model latency,
  AI cost, credit consumption, build/test/deploy/infra failures). Never build
  systems that can't explain what happened.

## 4. Product modes

- **Build mode** — a plain-language request produces *actual working software*
  through the agent pipeline (requirements → spec → architecture → db → backend
  → frontend → tests → review → build → export/deploy). Never stop at specs.
- **Existing-software mode** — import (GitHub/GitLab/Bitbucket/ZIP/local),
  analyze (language/framework/deps/architecture/db/API/security/testing/infra),
  produce an intelligence report, then improve/rebuild/modernize/fix/optimize/
  add-features/migrate.
- **Legacy mode** — COBOL/mainframe/legacy Java/PHP/.NET/legacy DBs/ERP. Never
  blind full rewrites: discovery → inventory → dependency graph → business-rule
  extraction → risk analysis → modernization plan → incremental migration →
  parallel validation → controlled cutover. Mission-critical cutovers require
  human approval.

## 5. Architecture map

Modular monolith. Do not prematurely split into microservices. Target backend
apps (built phase by phase — only `core` exists today):

```
backend/apps/
  accounts/  organizations/  projects/  workspaces/  repositories/
  requirements/  architecture/  agents/  agent_runs/  model_router/
  ai_providers/  credits/  usage/  costs/  billing/  builds/  tests/
  security/  deployments/  infrastructure/  cloud/  monitoring/
  artifacts/  integrations/  audit/
```

Frontend (Flutter Web + Flutter mobile, added later, top-level `frontend/`):
Dashboard, Projects, Project Workspace, Agent Activity, Requirements,
Architecture, Code, Builds, Tests, Deployments, Infrastructure, Monitoring,
Costs, Billing, Settings. The **project workspace** is the central interface —
it shows what DevForge understands, what agents are doing, what changed, what it
costs, what needs approval, what failed, and what's ready.

## 6. V1 scope

V1 proves the first core loop, nothing more:

```
CREATE PROJECT → DESCRIBE SOFTWARE → Requirements Agent → Architect Agent
→ Agent task graph → Backend/Frontend/Database Agents → Testing Agent
→ Code Review Agent → WORKING APPLICATION → EXPORT
```

V1 standardizes the generated stack (Django + DRF, PostgreSQL, Flutter Web,
Flutter mobile, Docker). Additional frameworks come after the agent architecture
is proven.

## 7. Build order (phases)

Build in order; don't jump around. **Every feature ships with tests and is only
done when implemented + integrated + tested + verified** (see `../CLAUDE.md`).

| # | Phase | Status |
|---|-------|--------|
| 1 | Repository foundation | **done — runnable Django modular monolith + `core` health endpoint + test** |
| 2 | Users & organizations | **done — email-based custom User; Organization + role-based Membership tenancy; `/api/v1/me/`; admin; 17 tests** |
| 3 | Projects & workspaces | **done — Project (per-org tenant scope) + Workspace (per-project, one default); tenant-scoped API; 35 tests** |
| 4 | Agent framework | not started |
| 5 | Agent Orchestrator | not started |
| 6 | AI provider abstraction | not started |
| 7 | Model Router | not started |
| 8 | Project context & memory | not started |
| 9 | Requirements Agent | not started |
| 10 | Architect Agent | not started |
| 11 | Backend Agent | not started |
| 12 | Frontend Agent | not started |
| 13 | Database Agent | not started |
| 14 | Testing Agent | not started |
| 15 | Code Review Agent | not started |
| 16 | Build sandbox | not started |
| 17 | Git integration | not started |
| 18 | Export | not started |
| 19 | Credits & usage | not started |
| 20 | Cost estimation | not started |
| 21 | Deployment | not started |

## 8. Long-term destination

```
                    DEVFORGE
        BUILD  ·  MODERNIZE  ·  OPERATE
                       |
              AGENT ORCHESTRATOR
                       |
                 MODEL ROUTER
                       |
             PROJECT INTELLIGENCE
                       |
             COST / CREDIT ENGINE
                       |
              CLOUD ABSTRACTION
        AWS · Azure · GCP · DevForge Cloud · Customer Infra
```

This is the destination, not the v1 deliverable. Build the simplest architecture
that can *evolve* into it.
```
ONE USER → ONE LEAD AGENT → MANY SPECIALIZED AGENTS → CONTROLLED TOOLS
→ REAL SOFTWARE → TESTED → DEPLOYED → OPERATED.
```
