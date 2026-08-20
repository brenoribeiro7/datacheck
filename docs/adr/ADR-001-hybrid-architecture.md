# ADR-001: Hybrid Architecture

- Status: Foundation retained; product UI deferred beyond v1.0
- Date: 2026-08-13

## Context

The original roadmap assumed a mandatory web interface alongside CSV validation and data processing. The reduced v1.0 roadmap is API-first, while retaining the already-built frontend foundation.

## Decision

Retain the React/TypeScript shell, FastAPI/Python modular monolith, and isolated Validation Engine/Polars boundary. The React shell is frozen for v1.0; any post-v1.0 frontend communicates only through the versioned HTTP API.

## Alternatives considered

- API-first v1.0: selected by the reduced roadmap; the earlier rejection is superseded.
- Full-stack TypeScript: rejected because Python data-processing capabilities are central.
- Distributed services: rejected because they add operational and consistency complexity without a current boundary or scale requirement.

## Consequences

The repository retains two language toolchains, but v1.0 does not require generated TypeScript contracts or frontend product work. Backend modules preserve the Validation Engine boundary. The modular monolith keeps deployment and transactions understandable; the worker remains frozen foundation.

## Revision triggers

Revisit if a non-browser client changes the contract needs, measured scale requires independently operated services, the two-toolchain cost becomes disproportionate, or the Validation Engine must be deployed independently.
