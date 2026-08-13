# ADR-002: Asynchronous Data Processing

- Status: Accepted
- Date: 2026-08-13

## Context

CSV inputs may reach 5 GiB, so validation cannot depend on one request lifetime. Processing needs durable domain status, bounded retries, recoverability after worker loss, and explainable persisted results.

## Decision

Use PostgreSQL for domain and coordination state, Redis as the Celery broker, a Celery worker for asynchronous execution, and a framework-independent Validation Engine using Polars. An analysis has at most three attempts, retries only transient failures, and uses renewable PostgreSQL-arbitrated leases. Repeated deliveries must have idempotent observable effects by `analysis_id`. Reconciliation can recover expired work when attempts remain.

## Alternatives considered

- Synchronous request processing: rejected because file size and processing time exceed a reliable request boundary.
- Redis as domain or lock truth: rejected because historical state and arbitration require durable relational consistency.
- Exactly-once execution: rejected as an unsound broker guarantee; idempotent observable effects are the required property.
- Kafka, RabbitMQ, or a distributed service topology: rejected as unnecessary initial complexity.

## Consequences

Workers and the API share backend domain rules and staging access. Attempts, leases, result publication, and cleanup require explicit persistence constraints and integration tests. Broker delivery may repeat, and recovery must recheck PostgreSQL state before doing or publishing work.

## Revision triggers

Revisit if measured throughput exceeds Celery/Redis capacity, shared staging cannot support the deployment topology, task routing needs fundamentally different semantics, or operational evidence justifies independent processing services.
