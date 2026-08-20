# ADR-002: Asynchronous Data Processing

- Status: Deferred beyond v1.0; v1.0 analysis is synchronous
- Date: 2026-08-13

## Context

The original roadmap proposed large-file asynchronous processing with durable retry and worker recovery. Those requirements are outside the reduced v1.0 scope.

## Decision

Use synchronous application-service execution for v1.0 while preserving PostgreSQL as domain truth and the infrastructure-independent Validation Engine. Redis and Celery remain frozen foundation. The asynchronous retry, lease, redelivery, and reconciliation design is a post-v1.0 option rather than a release requirement.

## Alternatives considered

- Synchronous processing: selected for the reduced v1.0 scope and its bounded input contract.
- Redis as domain or lock truth: rejected because historical state and arbitration require durable relational consistency.
- Exactly-once execution: rejected as an unsound broker guarantee; a future asynchronous design would instead require idempotent observable effects.
- Kafka, RabbitMQ, or a distributed service topology: rejected as unnecessary initial complexity.

## Consequences

The v1.0 path avoids broker delivery and distributed coordination. If asynchronous execution is reconsidered after v1.0, it requires a new scope decision and the persistence/integration guarantees described by the original proposal.

## Revision triggers

Revisit only after v1.0 when measured workload or deployment evidence justifies asynchronous processing.
