# ADR-001: Hybrid Architecture

- Status: Accepted
- Date: 2026-08-13

## Context

The first release requires a web interface, while CSV validation and data processing are central product capabilities. The solution needs a clear browser contract, strong Python data tooling, and a topology that a small project can operate and explain.

## Decision

Use a React/TypeScript single-page frontend, a FastAPI/Python modular-monolith backend, and a Data Processing extension built around an isolated Validation Engine and Polars. Frontend and backend communicate only through a versioned HTTP API.

## Alternatives considered

- API-only: rejected because a web interface is mandatory for the first release.
- Full-stack TypeScript: rejected because Python data-processing capabilities are central.
- Distributed services: rejected because they add operational and consistency complexity without a current boundary or scale requirement.

## Consequences

The system has two language toolchains and an explicit OpenAPI-to-TypeScript contract flow. Backend modules must preserve the Validation Engine boundary. The modular monolith keeps deployment and transactions understandable while allowing the worker to run separately.

## Revision triggers

Revisit if a non-browser client changes the contract needs, measured scale requires independently operated services, the two-toolchain cost becomes disproportionate, or the Validation Engine must be deployed independently.
