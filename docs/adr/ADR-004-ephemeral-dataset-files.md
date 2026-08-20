# ADR-004: Ephemeral Dataset Files

- Status: Deferred beyond v1.0; v1.0 uses bounded local CSV storage
- Date: 2026-08-13

## Context

The original roadmap proposed very large staged uploads shared by the API and worker. The reduced v1.0 requires only bounded UTF-8 CSV ingestion using local application storage.

## Decision

For v1.0, use a documented bounded local CSV flow, treat filenames as untrusted, and retain only what the synchronous analysis and explainable history require. Complex staging states, retried cleanup, and dataset-version lifecycles are deferred.

## Alternatives considered

- Indefinite original-file retention: rejected because it is unnecessary for the approved history model and increases data-handling risk.
- Immediate object storage: deferred because the initial single-site topology does not require it.
- Persisting entire failed rows: rejected because bounded value previews provide explanation with lower exposure.

## Consequences

The frozen shared staging volume remains in the repository but does not impose a worker-driven v1.0 lifecycle. A future staged-upload design requires a new scope and retention decision.

## Revision triggers

Revisit after v1.0 if deployment becomes multi-host, storage durability requirements change, or measured input sizes justify a more complex lifecycle.
