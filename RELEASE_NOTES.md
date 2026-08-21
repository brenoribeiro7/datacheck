# DataCheck v1.0.0

## Highlights

- secure session-based registration, login, current-user, and logout APIs;
- owner-scoped Datasets with bounded UTF-8 CSV ingestion;
- configurable `required`, `unique`, `type`, `range`, and `regex` rules;
- a deterministic, infrastructure-independent Validation Engine;
- synchronous analysis with immutable historical results and a quality score.

## Security and integrity

- passwords are hashed with Argon2id;
- opaque session tokens are stored only as hashes;
- cookie-authenticated mutations require a trusted Origin or Referer and session-bound
  CSRF token;
- resource ownership is enforced consistently, with cross-owner identifiers returning the
  same not-found response as missing resources;
- uploads are size-bounded, structurally validated, and stored under generated internal
  keys rather than submitted filenames;
- API failures use sanitized responses and server-generated trace IDs.

## Validation and analysis

Validation produces complete deterministic counts while retaining at most the first 20
violation samples per rule. Analysis captures a coherent upload and rule snapshot, runs
synchronously, and atomically persists immutable results. The quality score is the simple
unweighted ratio of passed to evaluated cells, rounded to two decimal places; it is `null`
when no cells are evaluated.

## Quality and verification

The release is qualified through formatting, linting, static type checking, full unit and
PostgreSQL integration suites, migration upgrade/downgrade cycles, OpenAPI verification,
and the versioned Docker Compose smoke topology.

## Known limitations

- DataCheck v1.0 is API-first and has no frontend product flow.
- Analysis is synchronous; Redis and Celery remain frozen foundation rather than product
  processing infrastructure.
- Ingestion supports only one active strict UTF-8 CSV per Dataset, up to 10 MiB and 256
  columns, using local single-host storage without historical CSV retention.
- Object storage, distributed retries, reconciliation, exactly-once processing, and
  additional input formats are not supported.
- Validation has five fixed rule families, stores bounded violation samples, and uses a
  simple unweighted score.
- OAuth/OIDC, MFA, and RBAC are outside this release.
- Docker Compose is a reference topology for local execution and qualification.
