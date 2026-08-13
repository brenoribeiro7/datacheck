# DataCheck Stack Decision

Status: Approved implementation baseline

Primary track: Hybrid Architecture

Extension: Data Processing

This document is the source of truth for the approved technology and version baseline.

## Backend

| Component | Version |
|---|---:|
| Python | 3.13.15 |
| FastAPI | 0.141.1 |
| Pydantic | 2.13.4 |
| Pydantic Settings | 2.15.0 |
| SQLAlchemy | 2.0.52 |
| Alembic | 1.19.1 |
| `psycopg[binary]` | 3.3.4 |
| `celery[redis]` | 5.6.3 |
| redis-py | 6.4.0 |
| Polars | 1.43.2 |
| argon2-cffi | 25.1.0 |
| pytest | 9.1.1 |
| Ruff | 0.16.2 |
| mypy | 2.3.0 |
| Uvicorn | 0.52.2 |
| python-multipart | 0.0.32 |
| httpx | 0.28.1 |
| uv | 0.12.3 |

## Frontend

| Component | Version |
|---|---:|
| Node.js | 24.19.0 |
| pnpm | 11.12.0 |
| TypeScript | 5.9.3 |
| React | 19.2.8 |
| React DOM | 19.2.8 |
| Vite | 8.2.1 |
| Tailwind CSS | 4.3.3 |
| Zod | 4.4.3 |
| Vitest | 4.1.10 |
| Playwright | 1.62.1 |
| openapi-typescript | 7.13.0 |
| `@vitejs/plugin-react` | 6.0.5 |
| `@tailwindcss/vite` | 4.3.3 |
| `@types/react` | 19.2.18 |
| `@types/react-dom` | 19.2.4 |
| `@types/node` | 24.13.3 |

## Infrastructure

| Service | Version | Fixed image reference |
|---|---:|---|
| PostgreSQL | 18.4 | `postgres:18.4-bookworm@sha256:882236b897e39051d2368c5ccc6cda944904723506b2dfc97f2a8f5bc9afa382` |
| Redis Server | 8.10.0 | `redis:8.10.0-trixie@sha256:344e3945a0b431c8ff1eecd58c5573538126bd756f02fc7e218ddf1fc2546366` |

PostgreSQL 18 uses the current official-image data layout. Future persistent storage must mount at `/var/lib/postgresql`; older recipes that mount only `/var/lib/postgresql/data` must not be copied without review.

## Application container bases

| Runtime | Purpose | Fixed base image reference |
|---|---|---|
| Python 3.13.15 | API and worker | `python:3.13.15-slim-bookworm@sha256:00faa2debb87529f9f0764e9491d8ba400a3678976616c3bd7cb193745ac20d1` |
| Node.js 24.19.0 | Frontend development and build validation | `node:24.19.0-bookworm-slim@sha256:3638d9a6fe4030bd716be989438248074489337ba3275657f93595428be4fc03` |

The tags and repository digests were revalidated before the backend and frontend images were built successfully. These references are the application bases for the local topology. The resulting `datacheck-backend:local` and `datacheck-frontend:local` images are local build outputs, not release or published images.

## Compatibility decisions

- TypeScript 5.9.3 is deliberate because openapi-typescript 7.13.0 requires TypeScript 5.x.
- redis-py 6.4.0 is deliberate because the selected Celery/Kombu Redis dependency constraints exclude the newer redis-py majors considered during version closure.
- uv 0.12.3 is the selected project manager and can provision and recognize Python 3.13.15.
- Redis Server 8.10.0 was validated during bootstrap with an actual Celery 5.6.3/Kombu/redis-py 6.4.0 producer-to-broker-to-worker-to-result flow. The deterministic task returned `42` without a compatibility exception. This isolated check is not a claim that future project integration tests already exist.
- React and React DOM remain aligned at 19.2.8.
- PostgreSQL and Redis container references use fixed tags and recorded repository digests for a reproducible baseline.

## Rejected alternatives

- An API-only product was rejected because the first release requires a web interface.
- A full-stack TypeScript implementation was rejected because Python and data processing are central to the product.
- Pandas was not selected; Polars is the approved validation-processing engine.
- JWT authentication was not selected for the MVP; opaque server-side sessions fit the browser-first topology.
- Microservices, Kubernetes, Kafka, RabbitMQ, and object storage were rejected as initial complexity without a current topology requirement.
- Floating direct-dependency ranges and prereleases were rejected to keep the baseline reproducible.

## Revision triggers

Revisit this decision only when supported evidence changes a material constraint, including a security or maintenance issue, a version incompatibility, a measured 5 GiB capacity failure, a move beyond the shared-filesystem topology, a third-party client requirement, or operational scale that a modular monolith cannot meet. Any revision requires an explicit decision record, compatibility validation, and lockfile update.
