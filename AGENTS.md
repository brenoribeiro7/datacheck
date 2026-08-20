# Repository Working Agreement

## Purpose and current phase

DataCheck is a flagship CSV data-quality application whose first release is intentionally limited to the smallest technically convincing end-to-end product. DC-00 through DC-02 are closed. DC-03 implementation is complete and is in validation/integration closure; DC-04 through DC-06 have not started.

The v1.0 roadmap ends at DC-06:

- DC-00 — Scope / Bootstrap
- DC-01 — Executable Foundation
- DC-02 — Identity and API Security
- DC-03 — Datasets, Rules and CSV
- DC-04 — Validation Engine
- DC-05 — Analysis, Results and Score
- DC-06 — Hardening and v1.0.0

Do not add a DC-07+ phase or silently restore superseded first-release requirements.

## Scope boundaries

- Keep the backend a modular FastAPI monolith with PostgreSQL as domain truth.
- Keep the Validation Engine independent of HTTP, persistence, queues, and UI concerns.
- React, Redis, Celery, the worker, and the existing Compose topology are frozen foundation: do not remove, rewrite, or expand them for v1.0 unless a release-blocking defect requires a proportionate fix.
- The v1.0 product flow is API-first. Frontend product screens, generated TypeScript clients, and browser automation are post-v1.0.
- Analysis is synchronous in v1.0. Distributed retries, leases, reconciliation, and Celery product processing are post-v1.0.
- CSV is the only v1.0 ingestion format. DC-03 accepts one strict UTF-8 CSV up to 10 MiB, with at most 256 header columns, in controlled local storage; large-file capacity claims and object storage are post-v1.0.
- DC-03 configures `required`, `unique`, `type`, `range`, and `regex` rules against known uploaded columns. It does not execute them; execution starts only in DC-04 after DC-03 is merged and formally closed.
- Before adding functionality, require evidence that it is necessary to make the minimum product flow functional, secure, or technically convincing.

## Approved stack

- Backend: Python 3.13.15; uv 0.12.3; FastAPI 0.141.1; Pydantic 2.13.4; Pydantic Settings 2.15.0; SQLAlchemy 2.0.52; Alembic 1.19.1; psycopg 3.3.4; Celery 5.6.3; redis-py 6.4.0; Polars 1.43.2; argon2-cffi 25.1.0; Uvicorn 0.52.2; python-multipart 0.0.32; httpx 0.28.1; pytest 9.1.1; Ruff 0.16.2; mypy 2.3.0.
- Frontend foundation: Node.js 24.19.0; pnpm 11.12.0; TypeScript 5.9.3; React and React DOM 19.2.8; Vite 8.2.1; Tailwind CSS 4.3.3; Zod 4.4.3; Vitest 4.1.10.
- Infrastructure foundation: PostgreSQL 18.4 and Redis Server 8.10.0 through the versioned Docker Compose topology.

Exact manifests, lockfiles, and [STACK_DECISION.md](STACK_DECISION.md) are authoritative. Do not silently substitute technologies or versions.

## Security rules

- Use opaque 256-bit server-side sessions and persist only session-token hashes.
- Use production cookies with `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`, no `Domain`, and the preferred name `__Host-datacheck_session`.
- Protect cookie-authenticated mutations with an explicit trusted-origin policy and a synchronizer token sent as `X-CSRF-Token`.
- Hash passwords with Argon2id; never store plaintext or reversible passwords.
- Enforce ownership at every ID-based boundary and return the same not-found response for missing and out-of-ownership resources.
- Never log credentials, raw session or CSRF tokens, cookies, CSV content, or secrets.
- Never commit secrets or environment-specific credentials.

## Data-handling rules

- Treat filenames and CSV content as untrusted input.
- Accept only strict UTF-8 CSV with an optional BOM and enforce the exact 10 MiB file limit plus the bounded multipart request limit during ingestion.
- Never derive a storage path from a submitted filename. Use only validated internal storage keys beneath the configured root.
- Persist complete validation counts but only bounded violation samples.
- Do not retain entire rows merely to explain one violation.
- Avoid claims about unsupported formats, object storage, distributed processing, or large-file capacity.

## Migration rules

- All relational schema changes use Alembic.
- Review migrations with their models and constraints, including rollback or recovery impact.
- Do not rewrite a published migration. Add a new migration only when an approved schema correction requires one.
- Avoid destructive data changes without explicit approval.
- Do not claim an entity or constraint is implemented before its migration exists.

## Testing expectations

- Test domain behavior independently where practical.
- Test API contracts, authentication, CSRF, ownership, persistence constraints, migrations, and deterministic validation semantics at their appropriate boundaries.
- Use an isolated disposable PostgreSQL database for integration and migration tests.
- Keep local quality commands aligned with CI.
- Do not require frontend, Redis, or Celery product tests while those foundations remain frozen.

## Dependency policy

- Pin direct dependencies exactly and commit both lockfiles.
- Use `uv` for Python and `pnpm` for the frozen frontend foundation.
- Do not hand-edit lockfiles or add dependencies for convenience.
- Validate compatibility before accepting a dependency change.
- Keep container images pinned by exact tag and recorded digest.

## Container and CI rules

- Keep existing host publications bound to loopback for local development.
- Never use or reset a database belonging to another project.
- Use uniquely named, disposable resources for integration qualification and remove only those resources after the run.
- Keep GitHub Actions dependencies pinned to full commit SHAs and permissions read-only unless a reviewed need requires more.
- CI must qualify the schema and behavior actually present in the current phase.
- `docker compose down -v` is destructive and requires explicit reset authorization for the exact project.

## Git rules

- Keep changes scoped to one reviewed increment.
- Preserve shared history; do not force-push or rewrite published commits.
- Inspect staged and unstaged changes before commit.
- Do not commit `.venv`, `node_modules`, uploaded data, generated reports, credentials, local environment files, or tool caches.
- Run the checks appropriate to the changed scope before publication.

## Documentation rules

- Keep README, product brief, architecture, roadmap, and accepted ADRs consistent with implemented behavior and the reduced v1.0 scope.
- Historical architecture does not authorize implementation of superseded requirements.
- Use neutral professional language in public artifacts.

## Stop conditions

Stop and request review if a change requires an unapproved stack substitution, published-migration rewrite, destructive data operation, weakened security, disclosure of sensitive data, force push, material architecture change, frontend product expansion, asynchronous product processing, or scope beyond DC-06.

## Reporting expectations

Every increment report states scope, files changed, validation results, failures, warnings, migrations, security/data impact, Git state, and intentionally deferred work. Claims must be supported by current repository evidence.

## Current backend commands

```sh
cd backend
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy datacheck tests
uv run pytest -m "not integration"
uv run pytest -m integration
```

Operational `/health` and `/ready` endpoints remain outside the product OpenAPI contract.
