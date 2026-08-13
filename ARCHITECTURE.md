# DataCheck Architecture

Status: Approved conceptual baseline. This document describes intended boundaries and contracts; it does not claim that application source, endpoints, schema, or infrastructure configuration already exists.

## 1. Overall architecture

```text
Browser
  |
React SPA
  |
versioned HTTP API
  |
FastAPI
  |-- PostgreSQL
  |-- Staging Storage
  `-- Redis
        |
     Celery Worker
        |
   Validation Engine
        |
      Polars
```

PostgreSQL is the source of truth for domain state. Redis is broker and work infrastructure, never historical domain truth. The frontend has no direct access to PostgreSQL or Redis. Initial staging storage is a filesystem shared by the backend and worker.

## 2. Backend style

The backend is a modular monolith. HTTP handling, application services, persistence adapters, background execution, and validation are distinct modules with explicit dependency direction. The worker is a separate runtime process but remains part of the same backend and domain. The MVP does not use microservices.

## 3. Validation Engine boundary

The Validation Engine owns dataset rule evaluation and result calculation. It must not depend on FastAPI, HTTP, cookies, Celery, Redis, SQLAlchemy, PostgreSQL, or React. Application adapters provide plain inputs and consume plain results. Rule behavior must be unit-testable without web, queue, or database infrastructure.

## 4. Domain model

```text
User
 |-- Session
 `-- Dataset
      |-- ValidationRule
      |-- StagedUpload
      `-- DatasetVersion
           `-- Analysis
                |-- AnalysisAttempt
                |-- AnalysisRuleSnapshot
                |    `-- RuleResult
                |         `-- ViolationSample
                `-- successful attempt
```

- `User` is the ownership root.
- `Session` represents a revocable server-side login.
- `Dataset` is a logical, user-owned resource.
- `ValidationRule` is the current rule configuration for a dataset.
- `StagedUpload` represents a temporary upload before consumption.
- `DatasetVersion` is one immutable accepted upload.
- `Analysis` tracks one asynchronous analysis of a dataset version.
- `AnalysisAttempt` records an individual execution attempt.
- `AnalysisRuleSnapshot` preserves the effective rule configuration used by an analysis.
- `RuleResult` stores complete evaluation counts and scoring data.
- `ViolationSample` stores a bounded, safe explanation sample.
- An analysis identifies its successful attempt when one completes.

These are conceptual relationships, not claims about implemented tables or fields.

## 5. Dataset semantics

A `Dataset` is a logical resource; a `DatasetVersion` is one immutable upload. In the MVP, one DatasetVersion has exactly one Analysis. A second analysis requires another upload and a new DatasetVersion after the original CSV has been removed. Existing history comes from persisted versions, rule snapshots, results, and samples rather than reusable original files.

## 6. File lifecycle

- Maximum accepted CSV size is 5 GiB inclusive.
- CSV files are temporary.
- After `COMPLETED`, remove the original file.
- After definitive `FAILED`, attempt immediate removal.
- If physical removal fails, record cleanup as pending and retry cleanup.
- An `AVAILABLE` staged upload expires after 24 hours if never consumed.
- A stale `UPLOADING` record becomes eligible for cleanup after 6 hours without activity.
- Original files are never retained indefinitely.

The staging implementation must use non-guessable identifiers, prevent path traversal, stream uploads, enforce size during ingestion, and restrict access to the backend and worker.

## 7. Analysis lifecycle

```text
QUEUED -> RUNNING -> COMPLETED
                  `-> FAILED
```

`COMPLETED` and `FAILED` are terminal. The MVP has no `CANCELLED` state. State transitions are persisted and arbitrated by PostgreSQL.

## 8. Attempts and retry

An analysis permits at most three total attempts: one initial execution and up to two retries. Only transient infrastructure or availability failures retry. Deterministic input, rule configuration, or evaluation failures do not retry.

The system makes no exactly-once execution guarantee. Its required property is an idempotent observable effect keyed by `analysis_id`: repeated deliveries must not create duplicate terminal results or violate attempt and result constraints.

## 9. Lease and recovery

A `RUNNING` analysis uses a renewable processing lease. A valid active lease prevents duplicate execution. When a lease expires, reconciliation may create a new attempt if attempts remain. PostgreSQL atomically arbitrates status, attempt allocation, lease ownership, expiry, and terminal publication. Redis must not be treated as lock truth.

Recovery must distinguish an abandoned attempt from a completed effect, recheck current PostgreSQL state before work and before publication, and leave an auditable attempt outcome.

## 10. Rule semantics

### `required`

- Text values fail when null, empty, or whitespace-only.
- Other supported types fail only when null.

### `unique`

- Applies to one column only.
- Null is skipped.
- No implicit trimming or case folding occurs.
- Every occurrence of a duplicated non-null value counts as a failure.
- Composite uniqueness is outside the MVP.

### `type`

Supported targets are `string`, `integer`, `number`, `boolean`, `date`, and `datetime`.

- Boolean accepts only `true` or `false`, case-insensitively.
- Date and datetime require ISO 8601.
- Parsing is not locale-dependent.

### `min_value` and `max_value`

- Apply to numeric values.
- Null is skipped.
- An invalid numeric value is an evaluation failure distinct from an ordinary out-of-range violation.

### `min_length` and `max_length`

- Apply to text.
- Use original value length without implicit trimming.
- Null is skipped.

### `regex`

- Applies to text using full-match semantics.
- Invalid expressions are rejected before analysis execution.
- Null is skipped.

### Common null rule

Only `required` treats null or missing values as violations. Every other rule skips null.

## 11. Missing rule column

When a configured column does not exist, the engine does not emit one violation per row. The analysis fails deterministically with code `missing_rule_column` and is not retried automatically.

## 12. Rule results

Each result conceptually stores:

- `evaluated_count`;
- `passed_count`;
- `failed_count`;
- `skipped_count`.

The invariant is:

```text
evaluated_count = passed_count + failed_count
```

Skipped rows are recorded separately and are not included in evaluated count.

## 13. Violation samples

Counts are complete even when samples are bounded. Persist no more than 1,000 violation samples per rule per analysis, and always distinguish:

- complete `failed_count`;
- returned or persisted violation count;
- `violations_truncated`.

`row_number` is the 1-based data-record position excluding the header; it must not be described as a physical line number. An observed value is only a preview, limited to 256 Unicode characters, with an explicit truncation indicator. Never store an entire CSV row merely to explain one violation.

## 14. Quality Score v1

For a rule where `evaluated_count > 0`:

```text
rule_score = 100 * passed_count / evaluated_count
```

When `evaluated_count = 0`, the rule score is null, status is `not_applicable`, and the rule does not participate in the global average.

The analysis quality score is the arithmetic mean of applicable rule scores with equal rule weights in v1. If no rule is applicable, `quality_score` is null and `quality_score_status` is `not_available`. A failed analysis also has a null quality score. Store `score_version = "v1"` and round only the final presentation result to two decimal places.

Quality Score measures average conformity with configured applicable rules. It is not the percentage of good rows and is not a universal data-quality metric.

## 15. Authentication

Authentication uses server-side sessions. The browser receives only an opaque random session identifier; the database stores its hash, never the raw token. Session tokens contain 256 bits of entropy generated by a cryptographically secure random number generator.

The production cookie uses:

- preferred name `__Host-datacheck_session`;
- `HttpOnly=true`;
- `Secure=true`;
- `SameSite=Lax`;
- `Path=/`;
- no `Domain` attribute.

Idle timeout is two hours and absolute lifetime is twelve hours. Logout revokes the server-side session and removes the cookie. JWT is not part of the MVP.

## 16. Passwords

Passwords accept 15 through 128 Unicode characters. There is no forced uppercase, number, and symbol composition rule. Passwords are hashed with Argon2id and are never stored in plaintext or reversible form. Exact Argon2id cost parameters require implementation-time security validation and are not invented at bootstrap.

## 17. CSRF and CORS

Cookie-authenticated mutations require CSRF protection using a synchronizer token supplied in the custom `X-CSRF-Token` header. The production topology prefers one public origin. Development CORS uses an explicit allowlist and must never combine wildcard origins with credentials.

## 18. Ownership

`User` is the ownership root. One user cannot access another user's resources. For an ID-based resource that does not exist or lies outside the current user's ownership, the API returns the same `404 resource_not_found` response to avoid revealing existence.

## 19. API contract

The HTTP API is versioned under `/api/v1`. Planned resource groups are `auth`, `datasets`, `uploads`, `rules`, `analyses`, `results`, and `violations`. These contracts are conceptual and are not implemented by this baseline.

Authentication contracts:

```text
POST /api/v1/auth/register
POST /api/v1/auth/login
POST /api/v1/auth/logout
GET  /api/v1/auth/me
```

Dataset contracts:

```text
POST   /api/v1/datasets
GET    /api/v1/datasets
GET    /api/v1/datasets/{dataset_id}
PATCH  /api/v1/datasets/{dataset_id}
DELETE /api/v1/datasets/{dataset_id}
```

Upload contract:

```text
POST /api/v1/datasets/{dataset_id}/uploads
Content-Type: multipart/form-data
```

An upload is single-use. Starting an analysis requires at least one active valid rule.

Analysis contract:

```text
POST /api/v1/datasets/{dataset_id}/analyses
-> 202 Accepted
```

Clients poll the analysis resource with GET until a terminal state. WebSocket and Server-Sent Events are outside the MVP.

## 20. Error envelope

Conceptual public errors use:

```json
{
  "code": "resource_not_found",
  "message": "Resource not found.",
  "details": {},
  "trace_id": "..."
}
```

`code` is stable and machine-readable, `message` is safe for public display, and `details` contains only safe structured context. API responses never expose stack traces.

## 21. Pagination

List endpoints use offset pagination with a default limit of 25, maximum limit of 100, minimum limit of 1, and `offset >= 0`. The MVP does not expose a generic query language.

## 22. OpenAPI contract

FastAPI and Pydantic OpenAPI output is the transport-contract source of truth:

```text
Pydantic -> OpenAPI -> openapi-typescript -> TypeScript transport types
```

Transport DTOs must not be duplicated manually. A later CI workflow will detect generated-type drift; no such workflow exists at bootstrap.

## 23. Persistence

Conceptual relational entities are:

- `users`;
- `sessions`;
- `datasets`;
- `validation_rules`;
- `staged_uploads`;
- `dataset_versions`;
- `analyses`;
- `analysis_attempts`;
- `analysis_rule_snapshots`;
- `rule_results`;
- `violation_samples`.

Planned constraints include unique normalized user email, unique session token hash, one analysis per dataset version, unique attempt number per analysis, attempt number from 1 through 3, score from 0 through 100 or null, row number at least 1, and sample index from 1 through 1,000. Foreign keys, ownership paths, state checks, terminal-result uniqueness, and timestamps must preserve the documented invariants.

No migration or schema implements these entities yet.

## 24. Dataset deletion

The MVP hard-deletes a dataset and its retained domain history. If a `QUEUED` or `RUNNING` analysis exists, deletion returns `409 dataset_has_active_analysis`. There is no endpoint for deleting an individual Analysis. Deleting a current ValidationRule never removes historical rule snapshots.

Deletion must also attempt staged-file cleanup and record pending cleanup when immediate physical deletion fails.

## 25. Logging and observability

Structured logs will include safe correlation identifiers such as `trace_id`, `analysis_id`, and `attempt_id` where appropriate. Logs must never include:

- passwords or password hashes;
- raw session tokens;
- CSRF tokens;
- `Cookie` values;
- CSV content;
- observed-value previews;
- dataset rows.

No OpenTelemetry requirement exists yet.

## 26. Capacity validation

Supporting a 5 GiB CSV is a first-release requirement, not already-proven evidence. Before the first release, execute a documented synthetic 5 GiB benchmark covering upload, staging, worker memory, processing time, database writes, cleanup, failure recovery, and relevant resource limits. This baseline does not claim that benchmark has passed.
