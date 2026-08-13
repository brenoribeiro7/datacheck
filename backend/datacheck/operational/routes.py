from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

DatabaseProbe = Callable[[], None]
DatabaseProbeProvider = Callable[[], DatabaseProbe]


def create_operational_router(probe_provider: DatabaseProbeProvider) -> APIRouter:
    """Create process-operational routes around an injectable database boundary."""
    router = APIRouter()

    @router.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        """Report process liveness without consulting external dependencies."""
        return {"status": "ok"}

    @router.get("/ready", include_in_schema=False)
    def readiness(
        response: Response,
        database_probe: Annotated[DatabaseProbe, Depends(probe_provider)],
    ) -> dict[str, str]:
        """Report whether PostgreSQL can currently serve API work."""
        try:
            database_probe()
        except Exception:
            # A readiness response is public operational state. Infrastructure error
            # details may contain credentials or hostnames and must not cross this boundary.
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "unavailable"}
        return {"status": "ready"}

    return router
