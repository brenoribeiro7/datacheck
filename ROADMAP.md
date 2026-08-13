# DataCheck Roadmap

The increments below are sequential delivery boundaries. DC-00 and DC-01 are completed; DC-02 through DC-11 remain planned and require their own acceptance evidence before status changes.

## DC-00 — Bootstrap Greenfield

- **Status:** Completed
- **Objective:** Establish a clean, reproducible local repository and approved engineering baseline.
- **Scope:** Git repository on `main`; public GitHub baseline; product, architecture, stack, roadmap, working-agreement, and ADR documentation; exact backend and frontend manifests and lockfiles; runtime version files; dependency compatibility and Celery/Redis smoke validation; MIT License; and initial publication to the approved repository.
- **Non-goals:** Application source, product functionality, database schema, migrations, Compose configuration, CI, endpoints, screens, releases, and tags.
- **Deliverables:** Bootstrap structure, locked dependency graphs, documentation baseline, four ADRs, verified infrastructure image references, MIT License, and the public `main` baseline at `brenoribeiro7/datacheck`.
- **Acceptance criteria:** Exact toolchain and direct versions resolve; locked/frozen installs are reproducible; an actual Celery task completes through Redis 8.10.0; tracked content passes security and neutrality review; the MIT License is present; the public repository exists at `brenoribeiro7/datacheck` with `main` as its default branch; local `main` and `origin/main` align at the approved baseline; and no unexpected bootstrap tags, releases, or branches exist.
- **Testing expectations:** Dependency import/version checks, lockfile reproducibility, document consistency and public-content review, isolated Celery/Redis task smoke, and concise post-publication remote audit.
- **Migration implications:** None; no schema exists.
- **Risks:** Version-resolution conflict, infrastructure compatibility failure, or documentation that overstates current implementation.
- **Dependencies:** Approved DC-00B0 version closure and successful Greenfield preflight.

## DC-01 — Executable foundation and CI

- **Status:** Completed
- **Objective:** Create the smallest executable backend/frontend foundation and repeatable local/CI verification.
- **Scope:** FastAPI and React/Vite application skeletons, health checks, module boundaries, configuration loading, Docker Compose for PostgreSQL/Redis/backend/worker/frontend as justified, baseline test/lint/typecheck/build commands, and GitHub Actions after publication approval.
- **Non-goals:** User identity, datasets, uploads, rule evaluation, or product screens beyond a foundation shell.
- **Deliverables:** Runnable development topology, validated commands, initial CI workflow, configuration examples without secrets, and contributor setup documentation.
- **Acceptance criteria:** Fresh locked installs succeed; services start predictably; health checks pass; CI runs formatting/lint/type/test/build foundations; no product behavior is implied.
- **Testing expectations:** Startup and health integration checks, configuration-failure tests, frontend smoke test, and CI parity with documented local commands.
- **Migration implications:** The Alembic environment is established with zero product revisions and no product tables.
- **Risks:** Environment drift, slow container feedback, accidental coupling, or secrets in configuration.
- **Dependencies:** DC-00 completed and version matrix approved.

## DC-02 — Identity, sessions and baseline security

- **Status:** Planned
- **Objective:** Implement secure registration, login, logout, current-user identity, and server-side sessions.
- **Scope:** User/session persistence, email uniqueness, 15–128 character passwords, Argon2id validation, opaque 256-bit session identifiers, token hashing, cookie policy, idle/absolute expiry, revocation, CSRF, and explicit development CORS.
- **Non-goals:** Organizations, roles, OAuth, password recovery, MFA, JWT, or external clients.
- **Deliverables:** Auth API contracts, migrations, security middleware/services, cleanup behavior, OpenAPI types, and minimal authentication UI support only if needed for contract validation.
- **Acceptance criteria:** Raw tokens and plaintext passwords are never persisted or logged; all auth contracts behave consistently; CSRF protects authenticated mutations; expired/revoked sessions fail safely.
- **Testing expectations:** Unit, API, persistence, cookie, CSRF, timing-independent token comparison where applicable, ownership groundwork, and adversarial error tests.
- **Migration implications:** Create `users` and `sessions` with unique email and token-hash constraints and lifecycle indexes.
- **Risks:** Credential leakage, session fixation, weak password-hash parameters, CSRF bypass, and account enumeration.
- **Dependencies:** DC-01 executable foundation.

## DC-03 — Datasets and Validation Rules

- **Status:** Planned
- **Objective:** Establish user-owned logical datasets and validated rule configuration.
- **Scope:** Dataset CRUD, rule CRUD, supported rule kinds, configuration validation, invalid-regex rejection, ownership masking, and offset pagination.
- **Non-goals:** File upload, rule execution, analysis state, results, and composite uniqueness.
- **Deliverables:** Dataset/rule domain modules, migrations, `/api/v1` contracts, OpenAPI-derived frontend types, and rule configuration documentation.
- **Acceptance criteria:** Users access only owned resources; non-existent and foreign IDs return the same `404 resource_not_found`; rules reject unsupported or inconsistent parameters; list limits obey 1–100 with default 25.
- **Testing expectations:** Domain validation, API contracts, database constraints, pagination boundaries, ownership isolation, and regex validation tests.
- **Migration implications:** Create `datasets` and `validation_rules` with ownership, ordering/status, rule-kind, parameter, and timestamp constraints.
- **Risks:** Ambiguous rule semantics, schema that prevents later snapshots, and ownership leaks.
- **Dependencies:** DC-02 identity and security baseline.

## DC-04 — Upload and Staging Storage

- **Status:** Planned
- **Objective:** Safely stream and stage single-use CSV uploads up to 5 GiB.
- **Scope:** Multipart upload, protected shared staging, size enforcement during streaming, upload states, non-guessable storage identifiers, 24-hour available expiry, six-hour stale-upload cleanup, and dataset-version creation boundary.
- **Non-goals:** Validation execution, result generation, indefinite retention, object storage, or additional file formats.
- **Deliverables:** Upload endpoint, staging adapter, metadata persistence, cleanup/reconciliation job, operational limits, and failure-safe file handling.
- **Acceptance criteria:** Oversized and invalid uploads fail safely; paths cannot escape staging; only owners can upload/access metadata; upload is single-use; abandoned files are eventually removed.
- **Testing expectations:** Streaming boundary tests around 5 GiB using practical lower-level fixtures plus later full benchmark, path traversal tests, interrupted upload recovery, expiry, cleanup failure, and ownership tests.
- **Migration implications:** Create `staged_uploads` and `dataset_versions` with lifecycle, uniqueness, ownership path, size, expiry, and consumption constraints.
- **Risks:** Disk exhaustion, partial-file leakage, race conditions, unsafe filenames, and cleanup gaps.
- **Dependencies:** DC-03 datasets and rules; DC-01 storage/runtime foundation.

## DC-05 — Validation Engine

- **Status:** Planned
- **Objective:** Implement deterministic, infrastructure-independent rule evaluation with Polars.
- **Scope:** CSV reading strategy; exact `required`, `unique`, `type`, range, length, and regex semantics; common null behavior; complete counts; bounded samples; missing-column failure; Quality Score inputs.
- **Non-goals:** Celery orchestration, HTTP handlers, database adapters, retry, and frontend presentation.
- **Deliverables:** Pure Validation Engine interfaces, rule evaluators, result types, stable evaluation error codes, and isolated test fixtures.
- **Acceptance criteria:** Every approved semantic edge is deterministic; count invariant holds; missing columns produce `missing_rule_column`; sample cap, row numbering, and 256-character previews are correct.
- **Testing expectations:** Unit and property-oriented tests for nulls, duplicates, parsing, Unicode length, ISO dates, numeric errors, regex full match, truncation, and score inputs.
- **Migration implications:** None directly; result types inform but do not create persistence schema.
- **Risks:** Excessive memory use, locale-dependent parsing, semantic drift, and leaking full row data.
- **Dependencies:** DC-00 architecture semantics and DC-04 staged-file contract.

## DC-06 — Asynchronous Analysis and recovery

- **Status:** Planned
- **Objective:** Execute analyses asynchronously with durable state, bounded retry, leases, and recovery.
- **Scope:** Analysis creation, rule snapshots, attempts 1–3, `QUEUED`/`RUNNING`/terminal transitions, Celery publication/consumption, renewable leases, reconciliation, idempotent effects, transient-error classification, and terminal file cleanup.
- **Non-goals:** Exactly-once guarantees, cancellation, WebSocket/SSE delivery, and result presentation UI.
- **Deliverables:** Analysis application service, worker task, migrations, lease/reconciliation process, polling contract, and operational failure documentation.
- **Acceptance criteria:** Active leases prevent duplicate work; expired work recovers only when eligible; deterministic failures do not retry; repeated delivery cannot duplicate terminal effects; upload files follow terminal cleanup rules.
- **Testing expectations:** PostgreSQL/Redis/Celery integration, crash and redelivery simulation, attempt limit, lease renewal/expiry, publication race, idempotency, and cleanup retry tests.
- **Migration implications:** Create `analyses`, `analysis_attempts`, and `analysis_rule_snapshots` with one analysis per version, unique attempt numbers, state and lease constraints, and snapshot immutability.
- **Risks:** Duplicate effects, stuck leases, retry storms, state races, broker/database split-brain, and orphaned files.
- **Dependencies:** DC-04 staging and DC-05 Validation Engine.

## DC-07 — Results, Violations and Quality Score

- **Status:** Planned
- **Objective:** Persist and expose explainable analysis results and Quality Score v1.
- **Scope:** Rule results, complete counts, up to 1,000 violation samples per rule/analysis, truncation metadata, Quality Score v1, result/violation endpoints, and historical rule snapshots.
- **Non-goals:** Custom score weighting, row-quality percentage, export reports, individual analysis deletion, or reprocessing deleted files.
- **Deliverables:** Result persistence, migrations, paginated APIs, scoring service, safe preview serialization, and OpenAPI-derived types.
- **Acceptance criteria:** Count invariants and score formula hold; non-applicable and failed analyses return null scores correctly; samples never imply complete failures; history remains after current rules change.
- **Testing expectations:** Formula boundaries, rounding only at presentation, no-applicable case, failed case, sample pagination/truncation, ownership, snapshot persistence, and unsafe-value handling.
- **Migration implications:** Create `rule_results` and `violation_samples`; link successful attempts; enforce score, row-number, sample-index, and uniqueness constraints.
- **Risks:** Misleading score interpretation, excessive result storage, value leakage, and count/sample inconsistency.
- **Dependencies:** DC-06 terminal execution and rule snapshots.

## DC-08 — Frontend foundation and authentication

- **Status:** Planned
- **Objective:** Establish the production-shaped SPA foundation and complete browser authentication flows.
- **Scope:** Vite/React/Tailwind source, routing decision if then authorized, application shell, generated OpenAPI types, HTTP/CSRF handling, registration, login, logout, current-user state, and accessible feedback.
- **Non-goals:** Dataset management, uploads, analysis screens, a UI kit, or broad global-state infrastructure without evidence.
- **Deliverables:** Frontend source structure, authenticated shell, auth screens, generated contract command, tests, and build/typecheck/lint scripts.
- **Acceptance criteria:** Auth flows work against the API; credentials are not persisted in script-readable storage; errors are safe and accessible; generated types do not drift; build and checks pass.
- **Testing expectations:** Vitest component/behavior tests, HTTP contract mocks at boundaries, CSRF handling, session-expiry behavior, accessibility checks, and minimal Playwright auth journey.
- **Migration implications:** None beyond DC-02 backend schema.
- **Risks:** Contract duplication, unsafe credential handling, excessive frontend dependencies, and inaccessible interaction states.
- **Dependencies:** DC-02 auth API, DC-01 frontend foundation, and stable OpenAPI generation.

## DC-09 — Complete functional frontend

- **Status:** Planned
- **Objective:** Deliver the complete first-release browser workflow from dataset creation through historical analysis investigation.
- **Scope:** Dataset/rule management, CSV upload, analysis start and polling, lifecycle presentation, rule results, quality score explanation, violation investigation, pagination, history, and dataset deletion conflicts.
- **Non-goals:** Organizations, collaboration, billing, dashboards unrelated to core flow, live push updates, or unsupported ingestion formats.
- **Deliverables:** Product screens and navigation, upload progress and failure recovery UX, results/history views, quality-score explanation, and end-to-end flows.
- **Acceptance criteria:** A user can complete every approved core flow using only owned resources; terminal/failure states are explicit; sample truncation and score meaning are not misleading; refresh preserves server truth.
- **Testing expectations:** Vitest behavior coverage and Playwright happy-path plus critical failure/ownership/session/upload journeys across the real API topology.
- **Migration implications:** None expected; any new persistence need requires prior review rather than frontend-driven schema invention.
- **Risks:** Polling load, confusing lifecycle states, large upload UX, incomplete accessibility, and exposing unsafe values.
- **Dependencies:** DC-03 through DC-08 APIs, results, and authentication.

## DC-10 — Security/concurrency/cleanup hardening

- **Status:** Planned
- **Objective:** Validate and harden cross-cutting security, concurrency, recovery, and data cleanup before release qualification.
- **Scope:** Threat review, Argon2id parameter validation, session/CSRF/CORS hardening, authorization audit, rate/abuse controls as evidence requires, race testing, lease reconciliation, file cleanup observability, log redaction, and failure injection.
- **Non-goals:** New product features, new architecture, compliance certification, or unrelated observability platforms.
- **Deliverables:** Security checklist and evidence, concurrency test suite, cleanup dashboards/queries or runbook, reconciler hardening, and resolved high-risk findings.
- **Acceptance criteria:** No known critical/high issue remains; ownership responses do not disclose resources; secrets/data are absent from logs; concurrent delivery preserves invariants; cleanup failures are visible and recoverable.
- **Testing expectations:** Adversarial auth/CSRF/ownership tests, concurrent database integration tests, task redelivery/crash injection, stale upload/lease recovery, deletion races, and log-content assertions.
- **Migration implications:** Add reviewed indexes or constraints required by measured races and cleanup operations; include safe rollout and rollback plans.
- **Risks:** Late discovery of race conditions, security regressions, cleanup backlog, and performance effects from added controls.
- **Dependencies:** Complete functional backend and frontend through DC-09.

## DC-11 — 5 GiB capacity validation, final review and release

- **Status:** Planned
- **Objective:** Prove the release requirement under a documented environment and complete final release review.
- **Scope:** Synthetic 5 GiB CSV benchmark, resource and duration measurement, upload/processing/results/cleanup validation, failure recovery, production configuration review, documentation accuracy, dependency/security review, and release checklist.
- **Non-goals:** Hiding failed capacity evidence, changing the 5 GiB requirement without human decision, or adding unrelated features.
- **Deliverables:** Reproducible benchmark plan and evidence, bottleneck analysis, remediation if required, final architecture/security/operations review, release notes, and license compliance review.
- **Acceptance criteria:** A 5 GiB inclusive input completes within approved operational limits with bounded memory/disk behavior, correct results, and confirmed cleanup; recovery cases pass; all release blockers are closed and documentation matches reality.
- **Testing expectations:** End-to-end benchmark with monitoring, repeated representative runs, constrained-resource and failure scenarios, full automated suite, fresh-environment deployment, and manual security/release review.
- **Migration implications:** Only evidence-driven performance indexes or schema changes with rehearsal, backup/recovery assessment, and rollback plan.
- **Risks:** Capacity miss, resource exhaustion, environment-specific results, unsafe cleanup under load, or unresolved license-compliance/security issues.
- **Dependencies:** DC-10 hardening and all earlier acceptance criteria.
