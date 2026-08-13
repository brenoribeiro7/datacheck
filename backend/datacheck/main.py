from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial

from fastapi import FastAPI

from datacheck.core.settings import ApiSettings
from datacheck.infrastructure.database import (
    DatabaseResources,
    create_database_resources,
    probe_database,
)
from datacheck.operational.routes import DatabaseProbe, create_operational_router


def create_app(
    *,
    settings: ApiSettings | None = None,
    database_probe: DatabaseProbe | None = None,
) -> FastAPI:
    """Create an isolated API instance with process-scoped infrastructure."""
    configured_probe = database_probe
    active_probe: DatabaseProbe | None = None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        nonlocal active_probe
        resources: DatabaseResources | None = None

        if configured_probe is not None:
            active_probe = configured_probe
        else:
            resolved_settings = settings or ApiSettings.from_environment()
            resources = create_database_resources(resolved_settings.database_url.get_secret_value())
            active_probe = partial(probe_database, resources.engine)

        try:
            yield
        finally:
            # The Engine owns a connection pool. Its lifetime follows the API process,
            # while plain module import remains free of database connections.
            active_probe = None
            if resources is not None:
                resources.dispose()

    def get_database_probe() -> DatabaseProbe:
        if active_probe is None:
            raise RuntimeError("application lifespan is not active")
        return active_probe

    application = FastAPI(title="DataCheck API", lifespan=lifespan)
    application.include_router(create_operational_router(get_database_probe))
    return application


app = create_app()
