from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from functools import partial

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from datacheck.analysis.service import AnalysisService
from datacheck.api.errors import register_error_handlers
from datacheck.api.middleware import (
    DatasetUploadSizeLimitMiddleware,
    SanitizedExceptionMiddleware,
    TraceIdMiddleware,
)
from datacheck.api.v1.router import router as v1_router
from datacheck.core.settings import ApiSettings
from datacheck.datasets.service import DatasetService
from datacheck.datasets.storage import LocalDatasetStorage
from datacheck.identity.passwords import PasswordService
from datacheck.identity.service import IdentityService
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
    database_resources: DatabaseResources | None = None,
    identity_service: IdentityService | None = None,
    dataset_service: DatasetService | None = None,
    analysis_service: AnalysisService | None = None,
) -> FastAPI:
    """Create an isolated API instance with process-scoped infrastructure."""
    resolved_settings = settings or ApiSettings.from_environment()
    configured_probe = database_probe
    configured_resources = database_resources
    configured_identity_service = identity_service
    configured_dataset_service = dataset_service
    configured_analysis_service = analysis_service
    active_probe: DatabaseProbe | None = None

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        nonlocal active_probe
        resources = configured_resources
        owns_resources = False

        if configured_probe is not None:
            active_probe = configured_probe
        else:
            if resources is None:
                resources = create_database_resources(
                    resolved_settings.database_url.get_secret_value()
                )
                owns_resources = True
            active_probe = partial(probe_database, resources.engine)

        active_identity_service = configured_identity_service
        if active_identity_service is None and resources is not None:
            active_identity_service = IdentityService(
                session_factory=resources.session_factory,
                password_service=PasswordService(),
            )
        application.state.identity_service = active_identity_service
        storage: LocalDatasetStorage | None = None
        if resources is not None and (
            configured_dataset_service is None or configured_analysis_service is None
        ):
            storage = LocalDatasetStorage(resolved_settings.dataset_storage_root)

        active_dataset_service = configured_dataset_service
        if active_dataset_service is None and resources is not None:
            assert storage is not None
            active_dataset_service = DatasetService(
                session_factory=resources.session_factory,
                storage=storage,
            )
        application.state.dataset_service = active_dataset_service
        active_analysis_service = configured_analysis_service
        if active_analysis_service is None and resources is not None:
            assert storage is not None
            active_analysis_service = AnalysisService(
                session_factory=resources.session_factory,
                storage=storage,
            )
        application.state.analysis_service = active_analysis_service

        try:
            yield
        finally:
            # The Engine owns a connection pool. Its lifetime follows the API process,
            # while plain module import remains free of database connections.
            active_probe = None
            application.state.identity_service = None
            application.state.dataset_service = None
            application.state.analysis_service = None
            if owns_resources and resources is not None:
                resources.dispose()

    def get_database_probe() -> DatabaseProbe:
        if active_probe is None:
            raise RuntimeError("application lifespan is not active")
        return active_probe

    application = FastAPI(title="DataCheck API", lifespan=lifespan)
    application.state.api_settings = resolved_settings
    register_error_handlers(application)
    application.include_router(create_operational_router(get_database_probe))
    application.include_router(v1_router)
    application.add_middleware(DatasetUploadSizeLimitMiddleware)
    application.add_middleware(SanitizedExceptionMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.trusted_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "X-CSRF-Token"],
        expose_headers=[],
        max_age=600,
    )
    # Trace IDs wrap CORS so even middleware-owned preflight responses receive one.
    application.add_middleware(TraceIdMiddleware)
    return application


class LazyConfiguredApplication:
    """Resolve environment-backed API configuration on first ASGI use, not import."""

    def __init__(self, factory: Callable[[], FastAPI]) -> None:
        self._factory = factory
        self._application: FastAPI | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._application is None:
            self._application = self._factory()
        await self._application(scope, receive, send)


app: ASGIApp = LazyConfiguredApplication(create_app)
