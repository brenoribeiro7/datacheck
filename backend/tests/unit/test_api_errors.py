import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError

from datacheck.core.settings import ApiSettings
from datacheck.identity.email import EmailPolicyError
from datacheck.identity.passwords import PasswordPolicyError
from datacheck.identity.schemas import ErrorResponse
from datacheck.identity.service import (
    AuthenticatedContext,
    AuthenticationRequired,
    DuplicateIdentity,
    IdentityService,
    InvalidCredentials,
    InvalidCsrf,
    SessionIssuance,
    UserReference,
)
from datacheck.identity.tokens import encode_token
from datacheck.main import create_app

_NOW = datetime(2026, 4, 1, 12, tzinfo=UTC)
_ORIGIN = "http://localhost:3000"
_PASSWORD = "valid-password-1"


class _ServiceStub:
    def __init__(self) -> None:
        self.failure: BaseException | None = None
        self.issuance = SessionIssuance(
            user=UserReference(
                user_id=uuid.uuid4(),
                email="person@example.test",
                created_at=_NOW,
                updated_at=_NOW,
            ),
            session_id=uuid.uuid4(),
            bearer_token=encode_token(b"b" * 32),
            csrf_token=encode_token(b"c" * 32),
            absolute_expires_at=_NOW + timedelta(hours=12),
        )

    def _raise(self) -> None:
        if self.failure is not None:
            raise self.failure

    def register(self, **_kwargs: str) -> SessionIssuance:
        self._raise()
        return self.issuance

    def login(self, **_kwargs: str) -> SessionIssuance:
        self._raise()
        return self.issuance

    def authenticate(self, _bearer: str | None) -> AuthenticatedContext:
        self._raise()
        return AuthenticatedContext(
            user=self.issuance.user,
            session_id=self.issuance.session_id,
            csrf_token=b"c" * 32,
            absolute_expires_at=self.issuance.absolute_expires_at,
        )

    def logout(self, **_kwargs: object) -> None:
        self._raise()


def _application(service: _ServiceStub) -> FastAPI:
    settings = ApiSettings(
        environment="test",
        database_url=SecretStr("postgresql+psycopg://internal-db.example.invalid/datacheck"),
        trusted_origins=(_ORIGIN,),
        dataset_storage_root=Path("/tmp/datacheck-test-datasets"),
    )
    return create_app(
        settings=settings,
        database_probe=lambda: None,
        identity_service=cast(IdentityService, service),
    )


def _assert_error(response: Response, *, status_code: int, code: str) -> None:
    assert response.status_code == status_code
    assert set(response.json()) == {"code", "message", "details", "trace_id"}
    assert response.json()["code"] == code
    assert response.json()["trace_id"] == response.headers["x-trace-id"]
    ErrorResponse.model_validate(response.json())


def test_trace_id_is_server_generated_and_operational_bodies_stay_stable() -> None:
    service = _ServiceStub()
    with TestClient(_application(service)) as client:
        first = client.get("/health", headers={"X-Trace-ID": "client-controlled"})
        second = client.get("/health")

    assert first.json() == {"status": "ok"}
    assert first.headers["x-trace-id"] != "client-controlled"
    assert first.headers["x-trace-id"] != second.headers["x-trace-id"]


def test_request_validation_does_not_echo_submitted_input() -> None:
    submitted_secret = "recognizable-password-secret-value"
    service = _ServiceStub()
    with TestClient(_application(service)) as client:
        response = client.post(
            "/api/v1/auth/register",
            headers={"Origin": _ORIGIN, "Content-Type": "application/json"},
            json={"email": "person@example.test", "password": _PASSWORD, "extra": submitted_secret},
        )

    _assert_error(response, status_code=422, code="validation_error")
    assert submitted_secret not in response.text
    assert "input" not in response.json()


@pytest.mark.parametrize(
    ("path", "failure", "expected_status", "expected_code", "expected_message"),
    [
        (
            "/api/v1/auth/register",
            DuplicateIdentity("private duplicate detail"),
            409,
            "email_already_registered",
            "Email is already registered.",
        ),
        (
            "/api/v1/auth/login",
            InvalidCredentials("private credential detail"),
            401,
            "invalid_credentials",
            "Invalid email or password.",
        ),
        (
            "/api/v1/auth/register",
            SQLAlchemyError("postgresql+psycopg://private-host/private"),
            503,
            "service_unavailable",
            "Service temporarily unavailable.",
        ),
        (
            "/api/v1/auth/login",
            SQLAlchemyError("private database driver detail"),
            503,
            "service_unavailable",
            "Service temporarily unavailable.",
        ),
    ],
)
def test_register_and_login_errors_are_stable_and_sanitized(
    path: str,
    failure: BaseException,
    expected_status: int,
    expected_code: str,
    expected_message: str,
) -> None:
    service = _ServiceStub()
    service.failure = failure
    with TestClient(_application(service)) as client:
        response = client.post(
            path,
            headers={"Origin": _ORIGIN, "Content-Type": "application/json"},
            json={"email": "person@example.test", "password": _PASSWORD},
        )

    _assert_error(response, status_code=expected_status, code=expected_code)
    assert response.json()["message"] == expected_message
    assert str(failure) not in response.text


@pytest.mark.parametrize(
    ("path", "failure", "field"),
    [
        ("/api/v1/auth/register", EmailPolicyError("private submitted email"), "email"),
        ("/api/v1/auth/register", PasswordPolicyError("private submitted password"), "password"),
        ("/api/v1/auth/login", PasswordPolicyError("private submitted password"), "password"),
    ],
)
def test_policy_validation_is_field_specific_without_echoing_values(
    path: str,
    failure: BaseException,
    field: str,
) -> None:
    service = _ServiceStub()
    service.failure = failure
    with TestClient(_application(service)) as client:
        response = client.post(
            path,
            headers={"Origin": _ORIGIN, "Content-Type": "application/json"},
            json={"email": "person@example.test", "password": _PASSWORD},
        )

    _assert_error(response, status_code=422, code="validation_error")
    assert response.json()["details"][0]["field"] == ["body", field]
    assert str(failure) not in response.text
    assert "person@example.test" not in response.text
    assert _PASSWORD not in response.text


def test_authentication_csrf_origin_and_media_errors_are_stable() -> None:
    service = _ServiceStub()
    application = _application(service)
    with TestClient(application) as client:
        service.failure = AuthenticationRequired("private session state")
        authentication = client.get("/api/v1/auth/me")

        service.failure = InvalidCsrf("private CSRF detail")
        client.cookies.set("datacheck_session", service.issuance.bearer_token)
        csrf = client.post("/api/v1/auth/logout", headers={"Origin": _ORIGIN})

        service.failure = None
        origin = client.post(
            "/api/v1/auth/logout",
            headers={"Origin": "https://wrong.example.test"},
        )
        media = client.post(
            "/api/v1/auth/login",
            headers={"Origin": _ORIGIN, "Content-Type": "text/plain"},
            content="private request body",
        )

    _assert_error(authentication, status_code=401, code="authentication_required")
    _assert_error(csrf, status_code=403, code="invalid_csrf_token")
    _assert_error(origin, status_code=403, code="invalid_origin")
    _assert_error(media, status_code=415, code="unsupported_media_type")
    assert "set-cookie" not in csrf.headers
    assert "private" not in " ".join(
        response.text for response in (authentication, csrf, origin, media)
    )


def test_unexpected_failure_is_sanitized() -> None:
    private_detail = "unexpected-private-stack-detail"
    service = _ServiceStub()
    application = _application(service)

    @application.get("/api/v1/test-unexpected")
    def unexpected() -> None:
        raise RuntimeError(private_detail)

    with TestClient(application) as client:
        response = client.get("/api/v1/test-unexpected")

    _assert_error(response, status_code=500, code="internal_error")
    assert response.json()["message"] == "Internal server error."
    assert private_detail not in response.text


def test_database_failures_for_me_and_logout_are_sanitized_without_cookie_deletion() -> None:
    private_detail = "private database connection detail"
    service = _ServiceStub()
    service.failure = SQLAlchemyError(private_detail)
    with TestClient(_application(service)) as client:
        client.cookies.set("datacheck_session", service.issuance.bearer_token)
        me = client.get("/api/v1/auth/me")
        logout = client.post(
            "/api/v1/auth/logout",
            headers={"Origin": _ORIGIN, "X-CSRF-Token": service.issuance.csrf_token},
        )

    _assert_error(me, status_code=503, code="service_unavailable")
    _assert_error(logout, status_code=503, code="service_unavailable")
    assert "set-cookie" not in logout.headers
    assert private_detail not in me.text
    assert private_detail not in logout.text
