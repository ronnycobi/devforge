# DevForge

An AI software-engineering platform: describe software, and specialized AI
agents build, test, review, and (later) deploy and operate it.

This repository is the source of truth. **How the platform is built** — the
engineering operating rules for anyone (human or AI) working in this repo — lives
in [`CLAUDE.md`](CLAUDE.md). **What DevForge is and the phased roadmap** lives in
[`docs/PRODUCT.md`](docs/PRODUCT.md).

## Status

Phase 1 — repository foundation. The backend is a runnable Django 6 modular
monolith with a single real endpoint (`/api/v1/health/`) and its test. Product
features are built phase by phase; see the roadmap in `docs/PRODUCT.md`.

## Layout

```
devforge/
├── CLAUDE.md            # engineering operating rules (read first)
├── docs/PRODUCT.md      # product definition + phased roadmap
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── backend/
    ├── manage.py
    ├── config/          # Django project (settings, urls, wsgi, asgi)
    └── apps/            # modular monolith — one Django app per bounded area
        └── core/        # health check + shared plumbing
```

The Flutter frontend/mobile app is added in a later phase (see roadmap); it will
live under a top-level `frontend/`.

## Running locally

Uses the shared interpreter at `../env` (no per-project venv). From the repo root:

```bash
../env/bin/python backend/manage.py migrate
../env/bin/python backend/manage.py runserver
```

Then open http://127.0.0.1:8000/api/v1/health/

By default the app uses a local SQLite file so it runs with no database server.
Set `DB_ENGINE=postgres` (see `.env.example`) to target PostgreSQL, or use
`docker compose up` for a Postgres-backed stack.

## Tests

```bash
../env/bin/python backend/manage.py test
```

## Configuration

All configuration is environment-driven — copy `.env.example` to `.env`. Secrets
(Django key, DB password, AI provider keys) are **never** committed.
