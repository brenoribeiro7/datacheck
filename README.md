# DataCheck

DataCheck is a flagship API-first application for repeatable, explainable CSV data-quality analysis. Its v1.0 scope is intentionally limited to the smallest complete product that demonstrates secure API design, domain modeling, CSV ingestion, deterministic validation, explainable persisted results, tests, CI, and professional documentation.

## Product flow

```text
Register -> Login -> Create Dataset -> Upload CSV -> Configure Rules
         -> Analyze -> Quality Score -> Violations -> Analysis History
```

The first release is complete when this flow is secure, owner-isolated, deterministic, reproducible, tested, and documented.

## v1.0 scope

- session-based registration, login, current-user lookup, and logout;
- user-owned datasets and validation rules;
- bounded UTF-8 CSV upload using local application storage;
- `required`, `unique`, `type`, `range`, and `regex` rules;
- synchronous deterministic analysis;
- persisted rule results, bounded violation samples, quality score, and history;
- PostgreSQL migrations, automated tests, CI, OpenAPI, and release documentation.

Frontend product flows, generated TypeScript clients, asynchronous analysis, distributed retries, leases, reconciliation, large-file capacity claims, object storage, and additional input formats are post-v1.0.

## Architecture

The active product is a modular FastAPI monolith backed by PostgreSQL. The Validation Engine remains independent of FastAPI, SQLAlchemy, and infrastructure. Analysis is synchronous in v1.0.

React, Redis, Celery, and the existing worker/Compose topology remain as frozen foundation from the earlier architecture. They are not removed, but they are not expanded into product functionality for v1.0.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the current boundaries and security model.

## Current status

```text
DC-00 CLOSED
DC-01 CLOSED
DC-02 implementation complete / validation and integration closure
DC-03 NOT STARTED
DC-04 NOT STARTED
DC-05 NOT STARTED
DC-06 NOT STARTED
```

DC-02 currently provides:

- `users` and `sessions` through Alembic revision `0001_identity_sessions`;
- Argon2id password hashing and a 15–128 character password policy;
- opaque 256-bit session tokens with only their hashes persisted;
- idle and absolute expiration, revocation, and bounded cleanup;
- secure environment-specific session cookies;
- explicit Origin/Referer and synchronizer-token CSRF validation;
- sanitized API errors and server-generated trace IDs;
- OpenAPI contracts for register, login, current user, and logout.

DC-02 is not declared closed until its branch is integrated into `main`.

## Authentication API

```http
POST /api/v1/auth/register
POST /api/v1/auth/login
GET  /api/v1/auth/me
POST /api/v1/auth/logout
```

Production uses the Secure, HttpOnly, SameSite=Lax `__Host-datacheck_session` cookie. Development and test use the explicit non-Secure `datacheck_session` cookie on loopback origins. Cookie-authenticated mutations require a trusted Origin or Referer and `X-CSRF-Token`.

## Technology foundation

- Python 3.13.15, FastAPI, Pydantic, SQLAlchemy, Alembic, and Polars;
- PostgreSQL 18.4;
- frozen React/Vite, Redis, and Celery foundations;
- exact direct dependencies and versioned lockfiles.

Exact dependency and image references are recorded in [STACK_DECISION.md](STACK_DECISION.md).

## Development setup

Prerequisites are Git, Docker Engine with Docker Compose, uv 0.12.3, and Python 3.13.15.

Create the local configuration and validate Compose:

```sh
cp .env.example .env
docker compose --env-file .env.example config --quiet
```

The example configuration permits only `http://127.0.0.1:5173` as the browser origin. Do not use wildcard origins with credentialed requests.

For a fresh local database, start PostgreSQL, build the API image, and apply migrations before starting the complete frozen topology:

```sh
docker compose up -d postgres
docker compose build api
docker compose run --rm api alembic upgrade head
docker compose up --build --wait
docker compose ps
```

Normal shutdown preserves named volumes:

```sh
docker compose down
```

`docker compose down -v` deletes project volumes and is only appropriate for an explicitly authorized reset of the exact Compose project.

## Backend quality commands

```sh
cd backend
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy datacheck tests
uv run pytest -m "not integration"
```

Integration tests require an isolated disposable PostgreSQL database:

```sh
DATACHECK_ENVIRONMENT=test \
DATACHECK_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:PORT/DATABASE' \
DATACHECK_TRUSTED_ORIGINS='["http://localhost:3000"]' \
uv run pytest -m integration
```

Never point the integration suite at a development or shared database: its migration fixture restores the selected database to an empty schema.

## Documentation

- [Product brief](PRODUCT_BRIEF.md)
- [Architecture](ARCHITECTURE.md)
- [Roadmap](ROADMAP.md)
- [Stack decision](STACK_DECISION.md)
- [Architecture decisions](docs/adr/)
- [Repository working agreement](AGENTS.md)

DataCheck is licensed under the [MIT License](LICENSE).
