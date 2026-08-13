import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from datacheck.main import create_app


def test_health_is_live_without_invoking_database_probe() -> None:
    def unexpected_probe() -> None:
        raise AssertionError("liveness must not consult PostgreSQL")

    with TestClient(create_app(database_probe=unexpected_probe)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_ready_for_successful_probe() -> None:
    calls = 0

    def successful_probe() -> None:
        nonlocal calls
        calls += 1

    with TestClient(create_app(database_probe=successful_probe)) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert calls == 1


def test_readiness_hides_failed_probe_details() -> None:
    internal_detail = "internal-database.example.invalid diagnostic detail"

    def failed_probe() -> None:
        raise RuntimeError(internal_detail)

    with TestClient(create_app(database_probe=failed_probe)) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert internal_detail not in response.text


def test_openapi_generation_excludes_operational_endpoints() -> None:
    application = create_app(database_probe=lambda: None)

    schema = application.openapi()

    assert "/health" not in schema["paths"]
    assert "/ready" not in schema["paths"]


def test_app_startup_requires_api_configuration(
    clear_datacheck_environment: None,
) -> None:
    with pytest.raises(ValidationError):
        with TestClient(create_app()):
            pass
