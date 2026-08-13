FROM python:3.13.15-slim-bookworm@sha256:00faa2debb87529f9f0764e9491d8ba400a3678976616c3bd7cb193745ac20d1 AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN python -m pip install --no-cache-dir "uv==0.12.3" \
    && uv --version

COPY pyproject.toml uv.lock ./

RUN uv sync --locked --no-dev --no-install-project


FROM python:3.13.15-slim-bookworm@sha256:00faa2debb87529f9f0764e9491d8ba400a3678976616c3bd7cb193745ac20d1 AS runtime

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --gid 10001 datacheck \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin datacheck \
    && mkdir -p /var/lib/datacheck/staging \
    && chown datacheck:datacheck /var/lib/datacheck/staging

COPY --from=builder /app/.venv /app/.venv
COPY --chown=datacheck:datacheck alembic.ini ./alembic.ini
COPY --chown=datacheck:datacheck alembic ./alembic
COPY --chown=datacheck:datacheck datacheck ./datacheck

USER datacheck

EXPOSE 8000

CMD ["uvicorn", "datacheck.main:app", "--host", "0.0.0.0", "--port", "8000"]
