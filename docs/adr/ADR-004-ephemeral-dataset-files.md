# ADR-004: Ephemeral Dataset Files

- Status: Accepted
- Date: 2026-08-13

## Context

The product must ingest CSV files up to 5 GiB and preserve explainable history, but retaining every original file indefinitely increases privacy, storage, and operational risk. The initial deployment can share filesystem storage between API and worker.

## Decision

Use temporary shared-filesystem staging with a 5 GiB inclusive upload limit. Delete the original CSV after `COMPLETED` or definitive `FAILED`, record and retry failed cleanup, expire unused available uploads after 24 hours, and clean stale uploads after six hours without activity. Preserve history through DatasetVersion metadata, rule snapshots, results, and bounded violation samples.

## Alternatives considered

- Indefinite original-file retention: rejected because it is unnecessary for the approved history model and increases data-handling risk.
- Immediate object storage: deferred because the initial single-site topology does not require it.
- Persisting entire failed rows: rejected because bounded value previews provide explanation with lower exposure.

## Consequences

A second analysis requires a new upload and DatasetVersion. Cleanup state and reconciliation are required. API and worker need access to the same protected staging filesystem. Product history cannot be used to reprocess a deleted original file.

## Revision triggers

Revisit when processes no longer share a filesystem, deployment becomes multi-host, storage durability requirements change, retention policy changes, or benchmark evidence shows the initial staging design cannot meet the 5 GiB requirement.
