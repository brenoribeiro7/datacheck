import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from datacheck.core.settings import ApiSettings
from datacheck.main import create_app


def _settings() -> ApiSettings:
    return ApiSettings(
        environment="test",
        database_url=SecretStr("postgresql+psycopg://127.0.0.1/datacheck"),
        trusted_origins=("http://localhost:3000",),
    )


def test_health_is_live_without_invoking_database_probe() -> None:
    def unexpected_probe() -> None:
        raise AssertionError("liveness must not consult PostgreSQL")

    with TestClient(create_app(settings=_settings(), database_probe=unexpected_probe)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_ready_for_successful_probe() -> None:
    calls = 0

    def successful_probe() -> None:
        nonlocal calls
        calls += 1

    with TestClient(create_app(settings=_settings(), database_probe=successful_probe)) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert calls == 1


def test_readiness_hides_failed_probe_details() -> None:
    internal_detail = "internal-database.example.invalid diagnostic detail"

    def failed_probe() -> None:
        raise RuntimeError(internal_detail)

    with TestClient(create_app(settings=_settings(), database_probe=failed_probe)) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert internal_detail not in response.text


def test_openapi_generation_describes_the_authentication_contract() -> None:
    application = create_app(settings=_settings(), database_probe=lambda: None)

    schema = application.openapi()

    assert "/health" not in schema["paths"]
    assert "/ready" not in schema["paths"]
    assert {
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/auth/logout",
    }.issubset(schema["paths"])
    components = schema["components"]
    for request_schema in ("RegisterRequest", "LoginRequest"):
        assert components["schemas"][request_schema]["properties"]["password"]["writeOnly"] is True

    assert components["securitySchemes"] == {
        "DevelopmentSessionCookie": {
            "type": "apiKey",
            "description": "HttpOnly session cookie used in development and test environments.",
            "in": "cookie",
            "name": "datacheck_session",
        },
        "ProductionSessionCookie": {
            "type": "apiKey",
            "description": "Secure __Host- session cookie used in production.",
            "in": "cookie",
            "name": "__Host-datacheck_session",
        },
    }
    cookie_security: list[dict[str, list[str]]] = [
        {"DevelopmentSessionCookie": []},
        {"ProductionSessionCookie": []},
    ]
    register = schema["paths"]["/api/v1/auth/register"]["post"]
    login = schema["paths"]["/api/v1/auth/login"]["post"]
    me = schema["paths"]["/api/v1/auth/me"]["get"]
    logout = schema["paths"]["/api/v1/auth/logout"]["post"]
    assert "security" not in register
    assert "security" not in login
    assert me["security"] == cookie_security
    assert logout["security"] == cookie_security

    assert logout["parameters"] == [
        {
            "name": "X-CSRF-Token",
            "in": "header",
            "required": False,
            "description": (
                "Required to revoke an active session; returned by authenticated session endpoints."
            ),
            "schema": {"type": "string"},
        }
    ]
    assert set(register["responses"]) == {"201", "403", "409", "415", "422", "500", "503"}
    assert set(login["responses"]) == {"200", "401", "403", "415", "422", "500", "503"}
    assert set(me["responses"]) == {"200", "401", "500", "503"}
    assert set(logout["responses"]) == {"204", "403", "500", "503"}


def test_app_startup_requires_api_configuration(
    clear_datacheck_environment: None,
) -> None:
    with pytest.raises(ValidationError):
        create_app()
