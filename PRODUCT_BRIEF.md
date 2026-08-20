# DataCheck Product Brief

## Problem

Data analysts and data engineers frequently receive external datasets whose quality is checked manually or with disposable scripts. Those checks are difficult to repeat, explain, compare, and retain.

DataCheck provides a durable, explainable assessment of missing values, duplicates, incompatible types, out-of-range values, and invalid formats.

## Primary user

The primary user is a Data Analyst or Data Engineer who needs to assess a CSV before trusting it or passing it downstream.

## Value proposition

An authenticated user uploads a CSV, configures validation rules, runs a deterministic analysis, and receives persisted rule results, bounded violation samples, a quality score, and analysis history.

## Minimum v1.0 flow

```text
Register
  -> Login
  -> Create Dataset
  -> Upload CSV
  -> Configure Rules
  -> Analyze
  -> Quality Score
  -> Violations
  -> Analysis History
```

## First-release requirements

- API-based user identity with secure server-side sessions;
- per-user ownership isolation;
- CSV as the only ingestion format;
- UTF-8 input with a documented bounded size;
- deterministic synchronous processing;
- `required`, `unique`, `type`, `range`, and `regex` validation;
- explainable rule-level counts and bounded violation samples;
- persisted analysis results and history;
- migrations, tests, CI, OpenAPI, and reproducible documentation.

## Explicit post-v1.0 scope

- frontend product flows and authentication screens;
- generated TypeScript API clients and browser end-to-end automation;
- XLSX, JSON, Parquet, and other ingestion formats;
- large-file capacity targets;
- S3, Azure Blob Storage, or other object storage;
- asynchronous Celery analysis, distributed retries, leases, and reconciliation;
- custom validator plugins or profiling frameworks;
- organizations, collaboration, RBAC, OAuth/OIDC, MFA, billing, and webhooks;
- generative AI or machine-learning scoring.

The first release demonstrates coherent engineering integration rather than every possible product capability.
