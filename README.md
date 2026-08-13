# DataCheck

DataCheck is a planned web application for repeatable, explainable CSV data-quality analysis. The repository now contains an executable backend/frontend foundation, local service topology, foundational tests, and initial CI validation. Product workflows remain intentionally unimplemented.

## Problem

Analysts and engineers routinely receive external datasets whose quality is checked manually or with disposable scripts. That process is hard to repeat, audit, and explain.

## Solution

DataCheck will let an authenticated user upload a CSV, configure validation rules, start an asynchronous analysis, inspect rule-level violations, and retain analysis history without retaining the original file indefinitely.

## Core capabilities

- browser-based CSV upload, up to 5 GiB inclusive;
- asynchronous validation;
- explainable rule results and bounded violation samples;
- persisted analysis history;
- per-user resource ownership;
- versioned HTTP contract between the frontend and backend.

## Architecture overview

The approved design is a React single-page application backed by a modular FastAPI monolith. PostgreSQL is the domain source of truth. Celery uses Redis as work infrastructure, while an isolated Validation Engine processes data with Polars. Uploaded CSV files use temporary shared staging storage in the initial topology.

See [ARCHITECTURE.md](ARCHITECTURE.md) for lifecycle, security, contract, and persistence decisions.

## Technology stack

- Python 3.13.15, FastAPI, Pydantic, SQLAlchemy, Alembic, Celery, and Polars;
- Node.js 24.19.0, TypeScript 5.9.3, React 19.2.8, Vite, and Tailwind CSS;
- PostgreSQL 18.4 and Redis Server 8.10.0;
- uv 0.12.3 and pnpm 11.12.0 with versioned lockfiles.

Exact dependency and image references are in [STACK_DECISION.md](STACK_DECISION.md).

## Validation rules

The first release supports `required`, `unique`, `type`, `min_value`, `max_value`, `min_length`, `max_length`, and `regex`.

## Analysis lifecycle

An analysis moves through `QUEUED`, `RUNNING`, and either `COMPLETED` or `FAILED`. Work is limited to three total attempts, retries only transient failures, and relies on PostgreSQL-backed state plus renewable processing leases. There is no exactly-once claim.

## Quality Score

Quality Score v1 is the arithmetic mean of applicable rule scores with equal rule weights. It measures conformity with configured rules; it is not the percentage of good rows or a universal data-quality metric.

## Security highlights

The MVP uses opaque server-side sessions, HttpOnly cookies, CSRF protection, Argon2id password hashing, explicit ownership checks, and safe error responses. Original CSV files are temporary and must not be retained indefinitely.

## Repository status

Current status: DC-00 repository bootstrap is completed, and DC-01 is in progress. Executable FastAPI and React/Vite foundations, a local five-service Docker Compose topology, foundational tests, and an initial CI workflow exist. No product API or functional product frontend exists; authentication, datasets, uploads, validation, and analysis behavior have not been implemented. There are no product database tables or migration revisions. The 5 GiB release benchmark has not been executed.

DataCheck is licensed under the MIT License. See [LICENSE](LICENSE).

## Documentation

- [Product brief](PRODUCT_BRIEF.md)
- [Architecture](ARCHITECTURE.md)
- [Stack decision](STACK_DECISION.md)
- [Roadmap](ROADMAP.md)
- [Architecture decision records](docs/adr/)
- [Repository working agreement](AGENTS.md)

## Roadmap

Delivery is divided into DC-00 through DC-11. DC-00 completed the reproducible repository baseline; DC-01 is in progress, followed by product capabilities, hardening, capacity validation, and release.

## Development prerequisites

- Git
- Docker Engine with Docker Compose
- uv 0.12.3
- Python 3.13.15
- Node.js 24.19.0
- pnpm 11.12.0

The version files, manifests, lockfiles, and [stack decision](STACK_DECISION.md) are authoritative.

## Development setup

Create a local environment file from the safe development template, then start the complete topology:

```sh
cp .env.example .env
docker compose up --build --wait
docker compose ps
```

The local services are available at:

- frontend: <http://127.0.0.1:5173/>;
- API liveness: <http://127.0.0.1:8000/health>;
- API readiness: <http://127.0.0.1:8000/ready>;
- PostgreSQL: `127.0.0.1:5432`;
- Redis: `127.0.0.1:6379`.

Stop the topology normally with:

```sh
docker compose down
```

Normal shutdown preserves the PostgreSQL named volume. `docker compose down -v` deletes the local PostgreSQL and staging volumes and is only appropriate for an explicit local reset.

The example PostgreSQL password is a disposable local placeholder, not production secret management. It remains URL-safe because Compose derives the backend database URL from the local PostgreSQL variables.

## Quality commands

Backend:

```sh
cd backend
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy datacheck tests
uv run pytest -m "not integration"
```

Frontend:

```sh
cd frontend
pnpm install --frozen-lockfile
pnpm typecheck
pnpm test
pnpm build
```

The equivalent aggregate frontend gate is `pnpm check`. The Compose configuration can be checked without starting services:

```sh
docker compose --env-file .env.example config --quiet
```
