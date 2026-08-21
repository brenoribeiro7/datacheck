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

DC-00 through DC-06 are closed. `v1.0.0` has been published, and DataCheck v1.0
is frozen.

Implemented product persistence currently consists of:

- `users`;
- `sessions`;
- owner-scoped `datasets` with active-upload metadata;
- dataset-scoped `validation_rules`;
- immutable owner-scoped `analyses` with source and score snapshots;
- ordered per-rule `validation_results` with complete counts and bounded samples.

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

Cookie-authenticated mutations validate an exact trusted `Origin`, with a validated `Referer` fallback, before domain work, and require the session-bound synchronizer token in `X-CSRF-Token`. Duplicate, missing, malformed, or wrong-session tokens fail closed.

## 8. Errors and sensitive data

Product API failures use a stable envelope containing a safe code, message, optional field issues, and a server-generated trace ID. Validation responses do not echo submitted values. Database and unexpected failures do not expose driver details or stack traces.

Passwords, raw session tokens, token hashes, CSRF tokens, complete cookies, secrets, CSV content, and dataset rows must not be logged. Sensitive session material is excluded from dataclass representations.

## 9. Transaction and concurrency boundaries

Registration persists its user and first session in one transaction. Login verifies credentials before a locked write phase and cannot create a session from a stale password snapshot. Authentication uses one conditional update for activity checks and monotonic touch. Logout locks the selected session before revocation.

PostgreSQL constraints remain the final arbiter for unique normalized email and unique session-token hash.

Dataset upload and rule creation lock the same owner-scoped `datasets` row. This serializes header replacement with rule creation so a committed rule cannot target a column absent from the active CSV. Exact duplicate rules are resolved by a PostgreSQL unique constraint.

Analysis uses that same dataset row lock only while it copies upload metadata, all
ordered rules, and the bounded active file into memory. It verifies the captured size and
SHA-256 before releasing the transaction. Polars parsing, the Validation Engine, and score
calculation then run without a database session or row lock. A second short transaction
atomically inserts the successful Analysis and all ValidationResults; failures leave no
partial history.

## 10. Dataset and CSV boundary

DC-03 adds the minimum owner-isolated `Dataset` and `ValidationRule` entities plus one active bounded CSV upload per dataset. The CSV contract is comma-delimited strict UTF-8 with optional BOM, a 10 MiB file limit, at most 256 exact unique header columns, and uniform row width. Parsing records only byte size, SHA-256, row count, columns, upload time, and safe filename metadata; it does not infer schema or quality.

Files live beneath one configured local root using generated UUID-based keys. Filenames are untrusted metadata and never determine storage paths. A candidate is written and scanned incrementally, installed by an atomic same-filesystem rename before the database update, and removed if the transaction fails. A successful reupload removes the previous file after commit. A process crash may leave an orphan file, but the database never points to a partial candidate; distributed reconciliation is intentionally outside v1.0.

The dataset HTTP boundary exposes create/list/get, one multipart upload, and create/list/delete rule operations. Every lookup is owner-scoped, and missing and out-of-ownership IDs share the same public `404` response. Rule configuration is validated and persisted for the five v1.0 families but is not executed in DC-03.

Additional formats, object storage, large-file capacity targets, complex dataset versioning, and distributed file cleanup are post-v1.0.

## 11. Validation Engine boundary

DC-04 supports exactly five rule families:

- `required`;
- `unique`;
- `type`;
- `range`;
- `regex`.

Each result contains complete evaluated/passed/failed counts and a bounded sample of violations. Rule semantics are deterministic and testable without HTTP or infrastructure.

The implemented engine accepts an ordered sequence of immutable rule specifications and
a materialized Polars `DataFrame` whose target columns use the textual `String` dtype.
It preserves rule and row order, numbers the first data row as 1, and returns immutable
in-memory results. Null, empty, and Unicode-whitespace-only cells are missing; trimming
is never applied to non-missing validation. Complete violation counts are retained while
only the first 20 violations per rule are sampled. Loading CSV data, persistence, score,
and history remain outside this boundary.

## 12. Analysis and score boundary

DC-05 performs analysis synchronously:

```text
create analysis
  -> capture an owner-scoped upload and complete rule snapshot
  -> materialize and verify bounded CSV bytes
  -> load a textual Polars DataFrame
  -> run Validation Engine
  -> calculate score
  -> atomically persist Analysis and ordered ValidationResults
  -> return persisted result
```

The immutable Analysis snapshot retains filename metadata, content hash, size, rows,
columns, upload time, score, and total violations. Each ValidationResult retains the
historical rule ID without an active-rule foreign key, the canonical rule definition,
complete counts, and the first 20 violation samples. Reupload and rule deletion therefore
cannot rewrite past results, and history reads never reload CSV data or recalculate scores.

The quality score is `100 × sum(passed_count) / sum(evaluated_count)`, calculated with
Decimal arithmetic and rounded half-up to two decimal places. Skipped cells are excluded;
when there are no applicable evaluations the score is `null`. Weighted severity systems,
asynchronous workers, leases, distributed retries, reconciliation, exactly-once claims,
and ML scoring are post-v1.0.

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

DataCheck v1.0.0 has been released, and the v1.0 product scope is frozen.
