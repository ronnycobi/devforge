---
name: devforge-feature
description: Use when adding or changing a feature in the DevForge repo. Captures this project's build loop and conventions — inspect, implement, migrate, test the app then the full suite, verify workspaces stay clean, and commit/push with the right trailer.
---

# Building a feature in DevForge

Follow this loop for every change (it matches CLAUDE.md and how the codebase is built).

## Conventions (do not deviate)
- Shared interpreter, no venv: run everything as `../env/bin/python backend/manage.py <cmd>` from the repo root.
- One Django app per bounded area under `backend/apps/<area>/`. Reuse existing services/models — don't duplicate.
- **Money/stock/auth logic is deterministic and lives in the engine**, never improvised. AI generates experiences, not ledgers.
- **Honesty rule:** never fake an integration, a payment, a deploy, or a status. If something needs credentials/infra that isn't here, gate it (report "not configured" and refuse) — never show a fake success.
- Secrets come from the environment only; never commit them.

## Steps
1. **Inspect** the relevant app(s) before writing code. Find the existing service, model, and tests.
2. **Implement** in the app's `service.py` / `models.py` / `views.py`, matching surrounding style.
3. **Migrations** when models change:
   `../env/bin/python backend/manage.py makemigrations <app> && ../env/bin/python backend/manage.py migrate`
4. **Tests** — every feature ships with tests. Run the app first, then the whole suite:
   `../env/bin/python backend/manage.py test apps.<app>` then `../env/bin/python backend/manage.py test apps`
5. **Verify workspaces stay clean** (tests must not write to the real workspaces dir):
   wrap any code that touches `DEVFORGE_WORKSPACES_ROOT` in `override_settings` with a tempdir; then
   `[ -z "$(ls -A backend/workspaces 2>/dev/null)" ]` should hold.
6. **Commit & push** (only when the change is done + green):
   ```
   git add -A && git commit -m "<area>: <what changed>

   <why / what it proves>

   Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
   git push origin main
   ```
   Then confirm `git rev-parse HEAD == origin/main`.

## Report format
```
Implemented: …
Changed: …
Tests: N pass (+k)
Remaining / gated: …
```
