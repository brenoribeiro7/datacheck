# DataCheck Architecture

## 1. Architectural objective

DataCheck v1.0 is the smallest flagship application that demonstrates a secure API, relational domain modeling, bounded CSV ingestion, deterministic validation, explainable persisted results, tests, CI, and professional documentation.

The design prioritizes a complete and teachable product flow over breadth.

## 2. System boundary

The active product is a modular FastAPI monolith backed by PostgreSQL:

```text
HTTP API
  -> application services
  -> domain modules
  -> SQLAlchemy repositories
  -> PostgreSQL

CSV adapter
  -> Validation Engine
  -> result persistence
```

The Validation Engine remains independent of FastAPI, cookies, SQLAlchemy, PostgreSQL, React, Redis, and Celery. It accepts plain rule/input values and returns deterministic result values.

React, Redis, Celery, and the worker already exist as frozen foundation. They remain versioned but do not participate in the v1.0 product flow. Analysis is synchronous.

## 3. Delivery state

DC-00 and DC-01 are closed. DC-02 identity and API security is implemented and undergoing validation and integration closure. DC-03 through DC-06 have not started.

Implemented product persistence currently consists of:

- `users`;
- `sessions`.

Future entities described below are boundaries for DC-03 through DC-05, not claims of current implementation.

## 4. Identity persistence

`User` is the ownership root. It stores a display-preserving email, normalized login identity, Argon2id password hash, and timestamps. Normalized email is unique.

`UserSession` stores:

- a user foreign key with delete cascade;
- a unique SHA-256 hash of the opaque session token;
- session-bound CSRF material;
- creation and last-seen timestamps;
- absolute expiration;
- optional revocation timestamp.

The database constrains token/CSRF length and lifecycle ordering. Alembic revision `0001_identity_sessions` creates and removes this schema.

## 5. Passwords and sessions

Passwords accept 15 through 128 Unicode characters after NFC normalization. Argon2id uses an explicit reviewed parameter profile. Plaintext and reversible passwords are never stored.

Session tokens contain 256 bits of entropy from a cryptographically secure generator. Only their SHA-256 hashes are persisted. A successful login always issues a new independent session.

Sessions have a two-hour idle timeout and a twelve-hour absolute lifetime. Authentication atomically checks activity and advances `last_seen_at` without allowing concurrent regression. Logout revokes only the current active session and is idempotent for missing or inactive sessions.

## 6. Authentication API

```http
POST /api/v1/auth/register
POST /api/v1/auth/login
GET  /api/v1/auth/me
POST /api/v1/auth/logout
```

Register returns `201`; login and current-user lookup return `200`; successful or already-inactive logout returns `204`. Missing, malformed, unknown, revoked, and expired authentication state converges to a safe public response where authentication is required.

OpenAPI is the HTTP contract source of truth. It documents request/response schemas, write-only password fields, cookie authentication for authenticated operations, the logout CSRF header, and route-specific errors. Generated TypeScript clients are not required in v1.0.

Operational `/health` and `/ready` endpoints are intentionally excluded from product OpenAPI.

## 7. Cookies, origins, CSRF, and CORS

Production uses:

- cookie name `__Host-datacheck_session`;
- `HttpOnly=true`;
- `Secure=true`;
- `SameSite=Lax`;
- `Path=/`;
- no `Domain` attribute.

Development and test use `datacheck_session` without `Secure` only on explicitly configured loopback origins. Every API environment requires a trusted-origin allowlist; wildcard credentialed origins are invalid.

Authentication mutations validate an exact trusted `Origin`, with a validated `Referer` fallback, before domain work. Active-session logout additionally requires the session-bound synchronizer token in `X-CSRF-Token`. Duplicate, missing, malformed, or wrong-session tokens fail closed.

## 8. Errors and sensitive data

Product API failures use a stable envelope containing a safe code, message, optional field issues, and a server-generated trace ID. Validation responses do not echo submitted values. Database and unexpected failures do not expose driver details or stack traces.

Passwords, raw session tokens, token hashes, CSRF tokens, complete cookies, secrets, CSV content, and dataset rows must not be logged. Sensitive session material is excluded from dataclass representations.

## 9. Transaction and concurrency boundaries

Registration persists its user and first session in one transaction. Login verifies credentials before a locked write phase and cannot create a session from a stale password snapshot. Authentication uses one conditional update for activity checks and monotonic touch. Logout locks the selected session before revocation.

PostgreSQL constraints remain the final arbiter for unique normalized email and unique session-token hash.

## 10. Dataset and CSV boundary

DC-03 will add the minimum owner-isolated `Dataset` and `ValidationRule` entities plus a bounded UTF-8 CSV upload. Filenames are untrusted metadata and must not determine storage paths. Local application storage is sufficient for v1.0.

Additional formats, object storage, large-file capacity targets, complex dataset versioning, and distributed file cleanup are post-v1.0.

## 11. Validation Engine boundary

DC-04 supports exactly five rule families:

- `required`;
- `unique`;
- `type`;
- `range`;
- `regex`.

Each result contains complete evaluated/passed/failed counts and a bounded sample of violations. Rule semantics are deterministic and testable without HTTP or infrastructure.

## 12. Analysis and score boundary

DC-05 performs analysis synchronously:

```text
create analysis
  -> load CSV
  -> run Validation Engine
  -> persist rule results and violations
  -> calculate score
  -> return persisted result
```

The v1.0 quality score uses one simple documented formula over applicable rule results. Weighted severity systems, asynchronous workers, leases, distributed retries, reconciliation, exactly-once claims, and ML scoring are post-v1.0.

## 13. Ownership

Every domain resource introduced after DC-02 belongs to a `User`. ID-based lookups must make missing and out-of-ownership resources indistinguishable through the same not-found response.

Ownership is enforced at application/repository boundaries and tested through real PostgreSQL integration.

## 14. Migrations and qualification

Relational changes use Alembic. Published migrations are not rewritten. Qualification starts from an empty disposable PostgreSQL database and verifies upgrade, schema, model drift, downgrade, and re-upgrade before integration tests.

CI uses the same PostgreSQL major version and validates the tables belonging to the current roadmap phase. No schema from a future phase is created early.

## 15. Frozen foundation

The existing React shell, Redis broker, Celery worker shell, shared staging volume, and five-service Compose topology are retained as sunk-cost foundation. Their presence is not a requirement to implement frontend product flows or asynchronous analysis.

Small configuration or documentation fixes may keep the foundation executable. Product expansion on those components is outside v1.0.

## 16. Release boundary

DC-06 performs full migration-from-zero qualification, security and ownership review, upload/data review, secrets/log review, final documentation, smoke tests, release notes, and the `v1.0.0` release.

After release, DataCheck v1.0 is frozen.
