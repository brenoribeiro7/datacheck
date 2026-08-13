import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from datacheck.core.settings import ApiSettings
from datacheck.infrastructure.database import create_database_resources, probe_database
from datacheck.main import create_app


@pytest.mark.integration
def test_postgresql_connection_and_real_readiness() -> None:
    settings = ApiSettings.from_environment()
    resources = create_database_resources(settings.database_url.get_secret_value())

    try:
        probe_database(resources.engine)
        assert inspect(resources.engine).get_table_names() == []
    finally:
        resources.dispose()

    with TestClient(create_app(settings=settings)) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
