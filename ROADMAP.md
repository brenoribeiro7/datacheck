# DataCheck v1.0 Roadmap

The v1.0 roadmap has seven sequential phases and ends at DC-06. No DC-07+ phase belongs to v1.0.

## DC-00 — Scope / Bootstrap

- **Status:** CLOSED
- **Outcome:** Repository, product baseline, exact manifests and lockfiles, license, and initial engineering decisions.

## DC-01 — Executable Foundation

- **Status:** CLOSED
- **Outcome:** FastAPI, SQLAlchemy, Alembic, PostgreSQL, React/Vite shell, frozen Redis/Celery foundation, Docker Compose, tests, and initial CI.
- **Boundary:** Existing React, Redis, Celery, and worker infrastructure remains frozen unless a release-blocking foundation defect requires a proportionate correction.

## DC-02 — Identity and API Security

- **Status:** CLOSED
- **Objective:** Provide session-based identity and proportional API security.
- **Scope:** User/session persistence; Argon2id passwords; opaque hashed session tokens; register, login, current-user, and logout contracts; secure cookie policy; trusted-origin and CSRF enforcement; safe errors; OpenAPI; unit, PostgreSQL, HTTP, migration, and concurrency tests.
- **Non-goals:** Frontend authentication, generated clients, OAuth/OIDC, MFA, password recovery, email verification, RBAC, organizations, JWT, or sophisticated rate limiting.
- **Closure gate:** Migration qualification, all local tests, PR CI, and merge into `main`.

## DC-03 — Datasets, Rules and CSV

- **Status:** CLOSED
- **Objective:** Add the smallest owner-isolated dataset and rule model with bounded UTF-8 CSV ingestion.
- **Scope:** `Dataset`, `ValidationRule`, local CSV upload, metadata, basic file/content validation, ownership, and minimal persistence.
- **Non-goals:** Object storage, additional formats, large-file targets, versioning frameworks, or complex file lifecycle orchestration.
- **Closure gate:** Migration qualification, all local tests, PR CI, review, and merge into `main`. Rule execution remains DC-04.

## DC-04 — Validation Engine

- **Status:** CLOSED
- **Objective:** Implement deterministic, infrastructure-independent validation.
- **Scope:** `required`, `unique`, `type`, `range`, and `regex`; complete counts; bounded violation samples; isolated unit tests.
- **Non-goals:** Plugin systems, custom validators, profiling frameworks, or infrastructure coupling.

## DC-05 — Analysis, Results and Score

- **Status:** NOT STARTED
- **Objective:** Run the engine synchronously, persist explainable results, calculate a simple documented score, and expose history.
- **Scope:** `Analysis`, `ValidationResult`, synchronous execution, rule counts, violations, quality score, and analysis history.
- **Non-goals:** Celery product processing, distributed retries, leases, reconciliation, exactly-once claims, severity frameworks, weighted scoring, or ML scoring.

## DC-06 — Hardening and v1.0.0

- **Status:** NOT STARTED
- **Objective:** Qualify and release the finished product.
- **Scope:** Full tests, migrations from zero, CI, security/ownership/upload review, secret/log review, final documentation, OpenAPI, smoke tests, limitations, release notes, and `v1.0.0`.

After DC-06 and the `v1.0.0` release, DataCheck v1.0 is frozen.
