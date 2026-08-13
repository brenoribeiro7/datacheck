# DataCheck

DataCheck is a planned web application for repeatable, explainable CSV data-quality analysis. The repository is currently at the repository-bootstrap and architecture-baseline stage; application code, runtime services, tests, and CI are scheduled for later increments.

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

Current status: DC-00 repository bootstrap is completed, and DC-01 has not started. No API, functional frontend, database schema or migration, Docker Compose topology, CI workflow, or project test suite exists yet. The 5 GiB release benchmark has not been executed.

DataCheck is licensed under the MIT License. See [LICENSE](LICENSE).

## Documentation

- [Product brief](PRODUCT_BRIEF.md)
- [Architecture](ARCHITECTURE.md)
- [Stack decision](STACK_DECISION.md)
- [Roadmap](ROADMAP.md)
- [Architecture decision records](docs/adr/)
- [Repository working agreement](AGENTS.md)

## Roadmap

Delivery is divided into DC-00 through DC-11. DC-00 completed the reproducible repository baseline; DC-01 is the next planned increment, followed by product capabilities, hardening, capacity validation, and release.

## Development prerequisites

- Git
- Docker Engine with Docker Compose
- uv 0.12.3
- Python 3.13.15
- Node.js 24.19.0
- pnpm 11.12.0

The version files and manifests are authoritative. Application startup commands do not exist at this stage.
