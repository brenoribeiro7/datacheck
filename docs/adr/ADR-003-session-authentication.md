# ADR-003: Session Authentication

- Status: Accepted
- Date: 2026-08-13

## Context

The MVP is a browser-first, same-origin web application with no third-party or mobile client requirement. It needs revocable login state and secure cookie-authenticated mutations.

## Decision

Use opaque server-side sessions. Generate a 256-bit random identifier, return it only in an HttpOnly cookie, and store only its hash. Apply a two-hour idle timeout, a twelve-hour absolute lifetime, server-side logout revocation, and synchronizer-token CSRF protection through `X-CSRF-Token`.

## Alternatives considered

- JWT access tokens: rejected because distributed verification and third-party client support are not requirements, while revocation and browser storage become more complex.
- Browser-stored bearer tokens: rejected because script-readable credential storage increases exposure.
- Cookie authentication without CSRF protection: rejected because authenticated mutations require explicit request-origin protection.

## Consequences

Authentication checks require a database session lookup and renewal policy. Production needs Secure, HttpOnly, SameSite cookies and a same-origin topology where practical. Session cleanup and revocation become operational responsibilities.

## Revision triggers

Revisit if supported mobile or third-party clients require token-based authorization, services require delegated identity, or measured session lookup load demands a reviewed architecture change.
