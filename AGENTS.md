# Repository Working Agreement

## Purpose and current phase

DataCheck is a browser-based, explainable CSV data-quality product for Data Analysts and Data Engineers. DC-00 and the DC-01 executable foundation are complete; DC-02 remains planned and has not started. Backend and frontend shells, foundational tests, a local five-service Compose topology, and the initial CI workflow exist; product functionality does not.

## Approved stack

- Backend: Python 3.13.15; uv 0.12.3; FastAPI 0.141.1; Pydantic 2.13.4; Pydantic Settings 2.15.0; SQLAlchemy 2.0.52; Alembic 1.19.1; psycopg 3.3.4; Celery 5.6.3; redis-py 6.4.0; Polars 1.43.2; argon2-cffi 25.1.0; Uvicorn 0.52.2; python-multipart 0.0.32; httpx 0.28.1; pytest 9.1.1; Ruff 0.16.2; mypy 2.3.0.
- Frontend: Node.js 24.19.0; pnpm 11.12.0; TypeScript 5.9.3; React and React DOM 19.2.8; Vite 8.2.1; Tailwind CSS 4.3.3; Zod 4.4.3; Vitest 4.1.10; Playwright 1.62.1; openapi-typescript 7.13.0.
- Infrastructure: PostgreSQL 18.4 and Redis Server 8.10.0 through the versioned Docker Compose topology.

Exact manifests, lockfiles, and [STACK_DECISION.md](STACK_DECISION.md) are authoritative. Do not silently substitute technologies or versions.

## Dependency and architecture boundaries

- Keep a React frontend separated from the backend by a versioned HTTP contract.
- Keep the backend a modular monolith. The Celery worker is a separate process within the same backend and domain.
- PostgreSQL is the source of truth for domain and coordination state. Redis is broker/work infrastructure, not historical truth.
- Keep the Validation Engine independent of FastAPI, HTTP, cookies, Celery, Redis, SQLAlchemy, PostgreSQL, and React.
- Frontend code must not directly access PostgreSQL or Redis.
- Generate TypeScript transport types from the FastAPI/Pydantic OpenAPI contract; do not duplicate transport DTOs manually.

## Security rules

- Use opaque 256-bit server-side sessions; persist only token hashes.
- Use production cookies with `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`, no `Domain`, and the preferred name `__Host-datacheck_session`.
- Protect cookie-authenticated mutations with a synchronizer token sent as `X-CSRF-Token`.
- Hash passwords with Argon2id; never store plaintext or reversible passwords.
- Enforce ownership at every ID-based boundary and return `404 resource_not_found` for missing and out-of-ownership resources alike.
- Never log credentials, raw session or CSRF tokens, cookies, CSV content, observed-value previews, or dataset rows.
- Never commit secrets or environment-specific credentials.

## Data-handling rules

- Enforce a maximum CSV size of 5 GiB inclusive.
- Treat uploaded CSV files as temporary. Delete them after terminal analysis states, with recorded and retried cleanup when physical deletion fails.
- Expire unused staged uploads after 24 hours and consider inactive `UPLOADING` records stale after 6 hours.
- Persist complete rule counts but no more than 1,000 violation samples per rule and analysis.
- Limit observed-value previews to 256 Unicode characters and record truncation.
- Do not retain entire rows merely to explain a violation.

## Migration rules

- All relational schema changes must use Alembic once its environment is established.
- Migrations must be reviewed with their model and constraint changes, include a rollback or recovery assessment, and avoid destructive data changes without explicit approval.
- Do not claim conceptual entities or constraints are implemented before their migrations exist.
- PostgreSQL 18 persistent storage must account for the official image layout rooted at `/var/lib/postgresql`.

## Testing expectations

- Isolate and unit-test Validation Engine rule semantics.
- Test API contracts, ownership boundaries, authentication, CSRF, persistence constraints, retry/lease behavior, and cleanup.
- Test frontend behavior and generated-contract integration with Vitest; reserve Playwright for essential browser flows.
- Use integration tests for PostgreSQL, Redis, and Celery boundaries.
- Complete an explicit synthetic 5 GiB benchmark before the first release; the requirement is not evidence of passing capacity.

## Dependency policy

- Pin direct dependencies exactly and commit both lockfiles.
- Use stable releases only unless an explicit reviewed decision says otherwise.
- Use `uv` for Python and `pnpm` for frontend package management.
- Do not hand-edit lockfiles or add a dependency for convenience. Record why each direct dependency is required.
- Validate compatibility, locked installation, and relevant integration boundaries before accepting dependency changes.
- Pin Python, Node.js, PostgreSQL, and Redis container bases by exact tag and repository digest. Do not replace the recorded references with floating tags.

## Container and CI rules

- The versioned Compose topology contains PostgreSQL, Redis, API, worker, and frontend services. Keep host publications bound to loopback for local development.
- Mount PostgreSQL 18 persistent storage at `/var/lib/postgresql`, and keep API/worker staging shared at `/var/lib/datacheck/staging`.
- Use `docker compose down` for normal shutdown. `docker compose down -v` deletes local named volumes and is reserved for an explicit reset.
- Keep GitHub Actions dependencies pinned to full commit SHAs, permissions read-only unless a reviewed need requires more, and local commands aligned with CI commands.
- There is no frontend lint command because ESLint is not an approved dependency. Do not disguise typecheck as lint.
- Playwright browser installation and execution remain deferred until an essential browser flow exists.
- OpenAPI TypeScript generation remains deferred until the first product `/api/v1` contract exists.

## Git rules

- Keep changes scoped to one reviewed increment.
- Use `main` as the initial branch and concise imperative commit messages.
- Do not commit `.venv`, `node_modules`, uploaded data, generated reports, credentials, or local environment files.
- Run whitespace, lockfile, test, security, and documentation checks appropriate to the changed scope before commit.
- Do not rewrite shared history, force-push, publish, or add remotes without explicit authorization.

## Stop conditions

Stop and request review if a change requires an unapproved stack substitution, an incompatible direct version, weakened security or data-retention rules, destructive migration, disclosure of sensitive data, or a material architecture change. Do not conceal failed checks or self-authorize structural workarounds.

## Reporting expectations

Every increment report must state scope, files changed, commands executed, validation results, failures, warnings, migrations, security/data impact, Git state, and intentionally deferred work. Claims must be supported by current repository evidence.

## Current actual commands

Backend quality:

```sh
cd backend
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy datacheck tests
uv run pytest -m "not integration"
```

Frontend quality:

```sh
cd frontend
pnpm install --frozen-lockfile
pnpm typecheck
pnpm test
pnpm build
```

`pnpm check` runs the frontend typecheck, test, and build gates together. No frontend lint command exists.

Local topology:

```sh
cp .env.example .env
docker compose --env-file .env.example config --quiet
docker compose up --build --wait
docker compose ps
docker compose down
```

The CI workflow must reproduce these locked quality and topology boundaries from a clean checkout. Operational `/health` and `/ready` endpoints are foundation probes, not product API contracts.
