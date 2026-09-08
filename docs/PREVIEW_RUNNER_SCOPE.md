# Customer-Server Preview Runner — Engineering Scope

Status: **scope / not built.** Supersedes nothing; extends the static preview
runner that ships today (`apps/preview_runner/runner.py`).

## 1. Goal

Let a customer see their generated application **actually running** — backend and
all — in the dashboard preview pane, and interact with it (click through pages,
submit forms, hit APIs), then say "change this" and see the change live.

## 2. What exists today (the starting point)

- `apps/preview_runner`: starts `python -m http.server` on an ephemeral
  `127.0.0.1` port rooted at the project repo, health-checks it, proxies it into
  the iframe via `dashboard.preview_live`, and stops it. **Serves files only —
  executes no customer code.** Safe, real, tested.
- `apps/build_sandbox`: `SubprocessSandbox` runs **short** commands under POSIX
  rlimits (CPU/mem/procs), `setsid`+`killpg` timeout, scrubbed env, network-free.
  Built for compile/test, not long-running servers.
- `apps/technology/stacks.py`: each runnable stack emits a `devforge.json`
  manifest with a `test_command`. There is **no run/serve entrypoint** yet.

## 3. Non-goals (explicitly out of scope for the runner itself)

- Production hosting / permanent URLs — that's the Deploy subsystem.
- Building for stacks whose toolchain isn't installed (still honest-deferred).
- Persisting preview state across restarts.

## 4. The hard part: this executes untrusted code, exposed to a browser

The static runner is safe because it runs no customer code. A customer-server
runner runs **arbitrary generated/customer code** as a network service the
browser talks to. That is the entire difficulty. Threats:

- Code that reads/writes outside its project, or reaches other tenants' data.
- Network egress (exfiltration, SSRF into internal services, abuse).
- Resource exhaustion (fork bombs, memory, disk, CPU) and never-terminating
  processes.
- The proxy becoming an open relay / SSRF pivot.
- Secrets in the runner's environment leaking into customer code.

**Principle:** a preview process is untrusted. Isolation must assume the code is
hostile, not merely buggy.

## 5. Isolation strategy (dev vs prod)

| | Dev / local (single-tenant) | Production (multi-tenant) |
|---|---|---|
| Boundary | subprocess + rlimits + `setsid`/killpg + scrubbed env (as `build_sandbox`) | **container per preview** (Docker/Podman/gVisor/Firecracker), non-root, read-only base + writable project mount |
| Network | localhost only; no egress guarantee | network namespace, **egress denied by default**, allowlist only |
| Filesystem | project dir only (cwd) | mount only the project; no host FS |
| Ports | ephemeral `127.0.0.1` | container port mapped to an internal proxy only |
| Reaper | idle TTL checked on access | dedicated sweeper + hard max lifetime |

Dev isolation is **best-effort and single-tenant only** — never expose it to
untrusted multi-tenant traffic. Production **requires** containerization; that is
the real infrastructure investment and the gate on multi-tenant preview.

## 6. Per-stack run entrypoint contract

Generators must emit a runnable server and declare how to run it. Extend
`devforge.json`:

```json
{
  "stack": "fastapi",
  "runnable": true,
  "run": {
    "install": ["pip", "install", "-r", "requirements.txt"],
    "command": ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "$PORT"],
    "port_env": "PORT",
    "health_path": "/",
    "ready_timeout_s": 30
  }
}
```

- The runner injects a chosen `$PORT`; the app MUST bind `127.0.0.1:$PORT`.
- `health_path` is polled until it responds or `ready_timeout_s` elapses.
- Per stack: FastAPI→uvicorn, Django→`manage.py runserver`, Node→`node server.js`
  reading `process.env.PORT`, Go→built binary. Each generator gains a server
  entrypoint + this block. This is a **generation change**, not just runner work.

## 7. The dependency-install blocker

`uvicorn`, `npm install`, `go mod download`, etc. need a package registry =
**network**, which the sandbox denies and this environment lacks. Options:

- **Vendored/stdlib-only stacks** run with no install (today's node/go/stdlib
  patterns) — the only offline-runnable path.
- **A build phase with controlled egress** (registry allowlist) in prod — part
  of the container pipeline, not the sandbox.

So: offline we can only preview no-dependency apps; real dependency apps need the
prod build/container path.

## 8. Runner architecture (target)

```
start(project):
  resolve run manifest  →  (no run block? honest "not previewable yet")
  provision isolate     →  dev: workdir; prod: container from project mount
  install (if declared, prod only, egress-limited)
  launch command with $PORT, rlimits/quotas, captured stdout/stderr
  health-check health_path until ready or timeout  →  fail cleanly + surface logs
  register {project, port/container, started_at, ttl, owner}
proxy(request):  tenant-guard → forward method/path/query/body/headers → stream back
stop(project):   kill container/process group; free port; drop registry entry
sweep():         reap idle > ttl and any over hard-max lifetime
```

## 9. Proxy requirements

- Forward all methods, query, body, and safe headers; stream responses.
- Rewrite/inject a `<base href>` or path-prefix so app-relative assets resolve
  through `/app/projects/<id>/live/…` (already the URL shape).
- WebSocket passthrough (Phase 4) for live/HMR apps.
- Strict per-request tenant + membership guard (as `preview_live` today).
- Never follow redirects to non-preview hosts (SSRF guard).

## 10. Resource & cost governance

Per preview: CPU, memory, PIDs, disk, wall-clock max, idle TTL, and (prod)
egress bytes. Per org: max concurrent previews. Attribute preview compute to the
Cost Engine like AI usage, and gate with the credit/daily-cap system already in
place.

## 11. Phased plan

- **P0 — Static preview.** ✅ Shipped (`preview_runner`).
- **P1 — No-dependency server preview (offline-real).** Add the `run` manifest
  block; give the Node/Go/stdlib generators a real server entrypoint binding
  `$PORT`; runner starts it under rlimits + reaper; proxy forwards. Fully
  testable offline for these stacks. *No containers, single-tenant, dev-labelled.*
- **P2 — Dependency builds.** Install step with egress-allowlisted build env
  (enables FastAPI/Django/React). Needs the prod build pipeline.
- **P3 — Containerized multi-tenant.** Per-preview container, network namespace,
  egress-deny, sweeper, per-org quotas. Gate before any untrusted multi-tenant
  exposure.
- **P4 — Interactive depth.** WebSocket/HMR passthrough, seeded preview database,
  click-element → "fix this" mapping onto the running preview.

## 12. Integration points

- Manifests/entrypoints: `apps/technology/stacks.py` + the scaffolders.
- Isolation primitives: reuse/extend `apps/build_sandbox`.
- Runner + proxy + registry/reaper: `apps/preview_runner`.
- UI: the two-pane `dashboard.preview` (start/stop already wired for static).
- Governance: `apps/credits` + `apps/costs`.

## 13. Risks & mitigations

- **Untrusted code escape** → containers + non-root + read-only base + dropped
  caps + seccomp (P3). Until then, single-tenant/dev only.
- **Egress abuse** → deny-by-default network namespace, allowlist (P3).
- **Process/port leaks** → registry + sweeper + hard max lifetime; killpg on stop.
- **Proxy SSRF** → fixed loopback target from the registry only; never a
  user-supplied host; no cross-host redirect following.
- **Cost blowups** → per-preview quotas + per-org concurrency + credit gating.

## 14. Acceptance criteria

- P1: a generated no-dependency app starts, is reachable through the proxy iframe,
  survives a change + restart, is reaped on idle, and leaks no processes — proven
  by offline tests (as P0 already is).
- P3: a deliberately hostile preview cannot read another tenant's data, cannot
  reach the network, and cannot outlive its limits — proven by isolation tests.

## 15. Honest recommendation

P1 is genuinely buildable and testable **offline** (stdlib/Node/Go servers, no
installs) and is the right next increment — it delivers a real running-app preview
for those stacks. P2–P3 are real infrastructure (build pipeline + containers) and
should not be faked; schedule them when there is an environment to run and test
them. Do not enable multi-tenant server preview before P3.
