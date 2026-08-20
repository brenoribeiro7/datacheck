from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import cast

import pytest
from argon2 import PasswordHasher, Type
from fastapi.testclient import TestClient
from httpx import Response
from pydantic import SecretStr
from sqlalchemy import delete, func, select, update

from datacheck.core.settings import ApiSettings
from datacheck.identity.models import User, UserSession
from datacheck.identity.passwords import PasswordService
from datacheck.identity.service import IdentityService
from datacheck.identity.tokens import decode_token, hash_session_token
from datacheck.infrastructure.database import DatabaseResources, probe_database
from datacheck.main import create_app

pytestmark = pytest.mark.integration
_NOW = datetime(2026, 4, 1, 12, tzinfo=UTC)
_ORIGIN = "http://localhost:3000"
_PASSWORD = "valid-password-1"
_COOKIE_NAME = "datacheck_session"


@dataclass
class _Clock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current


def _password_service() -> PasswordService:
    return PasswordService(
        PasswordHasher(
            time_cost=1,
            memory_cost=8_192,
            parallelism=1,
            hash_len=16,
            salt_len=8,
            encoding="utf-8",
            type=Type.ID,
        )
    )


def _test_client(
    resources: DatabaseResources,
    *,
    clock: _Clock | None = None,
) -> tuple[TestClient, IdentityService, _Clock]:
    active_clock = clock or _Clock(_NOW)
    service = IdentityService(
        session_factory=resources.session_factory,
        password_service=_password_service(),
        clock=active_clock,
    )
    settings = ApiSettings(
        environment="test",
        database_url=SecretStr("postgresql+psycopg://redacted.invalid/datacheck_test"),
        trusted_origins=(_ORIGIN,),
    )
    application = create_app(
        settings=settings,
        database_probe=partial(probe_database, resources.engine),
        database_resources=resources,
        identity_service=service,
    )
    return TestClient(application), service, active_clock


@pytest.fixture(autouse=True)
def clean_auth_api_rows(identity_database: DatabaseResources) -> Iterator[None]:
    with identity_database.engine.begin() as connection:
        connection.execute(delete(UserSession))
        connection.execute(delete(User))
    yield


def _register(client: TestClient, *, email: str = "person@example.test") -> Response:
    return cast(
        Response,
        client.post(
            "/api/v1/auth/register",
            headers={"Origin": _ORIGIN, "Content-Type": "application/json"},
            json={"email": email, "password": _PASSWORD},
        ),
    )


def _set_cookie(client: TestClient, value: str | None) -> None:
    client.cookies.clear()
    if value is not None:
        client.cookies.set(_COOKIE_NAME, value)


def test_register_contract_persistence_and_precondition_order(
    identity_database: DatabaseResources,
) -> None:
    client, _, _ = _test_client(identity_database)
    with client:
        response = _register(client)

        assert response.status_code == 201
        assert response.headers["cache-control"] == "no-store"
        assert set(response.json()) == {"user", "csrf_token"}
        assert set(response.json()["user"]) == {"id", "email", "created_at", "updated_at"}
        assert response.json()["user"]["updated_at"] == response.json()["user"]["created_at"]
        assert len(decode_token(response.json()["csrf_token"])) == 32
        bearer = response.cookies.get(_COOKIE_NAME)
        assert bearer is not None
        assert bearer not in response.text

        with identity_database.session_factory() as database_session:
            user = database_session.scalar(select(User))
            user_session = database_session.scalar(select(UserSession))
            assert user is not None
            assert user_session is not None
            assert str(user.id) == response.json()["user"]["id"]
            assert user.updated_at == datetime.fromisoformat(response.json()["user"]["updated_at"])
            assert user_session.user_id == user.id
            assert user_session.token_hash == hash_session_token(decode_token(bearer))
            assert bearer not in repr(user_session.__dict__)

        duplicate = _register(client, email="PERSON@example.test")
        assert duplicate.status_code == 409
        assert duplicate.json()["code"] == "email_already_registered"

        unsafe_email = "unsafe-origin@example.test"
        wrong_origin = client.post(
            "/api/v1/auth/register",
            headers={"Origin": "https://wrong.example.test", "Content-Type": "application/json"},
            json={"email": unsafe_email, "password": _PASSWORD},
        )
        wrong_media = client.post(
            "/api/v1/auth/register",
            headers={"Origin": _ORIGIN, "Content-Type": "text/plain"},
            content='{"email":"wrong-media@example.test","password":"private"}',
        )
        bad_password = client.post(
            "/api/v1/auth/register",
            headers={"Origin": _ORIGIN, "Content-Type": "application/json"},
            json={"email": "bad-policy@example.test", "password": "short"},
        )
        submitted_bad_email = "recognizable-invalid-email-value"
        bad_email = client.post(
            "/api/v1/auth/register",
            headers={"Origin": _ORIGIN, "Content-Type": "application/json"},
            json={"email": submitted_bad_email, "password": _PASSWORD},
        )

    assert wrong_origin.status_code == 403
    assert wrong_origin.json()["code"] == "invalid_origin"
    assert wrong_media.status_code == 415
    assert wrong_media.json()["code"] == "unsupported_media_type"
    assert bad_password.status_code == 422
    assert bad_password.json()["code"] == "validation_error"
    assert "short" not in bad_password.text
    assert bad_email.status_code == 422
    assert bad_email.json()["code"] == "validation_error"
    assert submitted_bad_email not in bad_email.text
    with identity_database.session_factory() as database_session:
        emails = set(database_session.scalars(select(User.email_normalized)))
        assert unsafe_email not in emails
        assert "wrong-media@example.test" not in emails
        assert "bad-policy@example.test" not in emails


def test_login_issues_an_independent_session_and_converges_failures(
    identity_database: DatabaseResources,
) -> None:
    client, _, _ = _test_client(identity_database)
    with client:
        registration = _register(client, email="login@example.test")
        original_bearer = registration.cookies.get(_COOKIE_NAME)
        assert original_bearer is not None

        login = client.post(
            "/api/v1/auth/login",
            headers={"Origin": _ORIGIN, "Content-Type": "application/json"},
            json={"email": "LOGIN@example.test", "password": _PASSWORD},
        )
        fresh_bearer = login.cookies.get(_COOKIE_NAME)
        assert login.status_code == 200
        assert login.headers["cache-control"] == "no-store"
        assert fresh_bearer is not None and fresh_bearer != original_bearer
        assert login.json()["csrf_token"] != registration.json()["csrf_token"]
        assert set(login.json()["user"]) == {"id", "email", "created_at", "updated_at"}

        wrong = client.post(
            "/api/v1/auth/login",
            headers={"Origin": _ORIGIN, "Content-Type": "application/json"},
            json={"email": "login@example.test", "password": "wrong-password-1"},
        )
        unknown = client.post(
            "/api/v1/auth/login",
            headers={"Origin": _ORIGIN, "Content-Type": "application/json"},
            json={"email": "unknown@example.test", "password": _PASSWORD},
        )
        malformed_email = client.post(
            "/api/v1/auth/login",
            headers={"Origin": _ORIGIN, "Content-Type": "application/json"},
            json={"email": "malformed-address", "password": _PASSWORD},
        )
        assert (
            (wrong.status_code, wrong.json()["code"], wrong.json()["message"])
            == (
                unknown.status_code,
                unknown.json()["code"],
                unknown.json()["message"],
            )
            == (401, "invalid_credentials", "Invalid email or password.")
        )
        assert (
            malformed_email.status_code,
            malformed_email.json()["code"],
            malformed_email.json()["message"],
        ) == (401, "invalid_credentials", "Invalid email or password.")

        with identity_database.session_factory() as database_session, database_session.begin():
            database_session.execute(
                update(User)
                .where(User.email_normalized == "login@example.test")
                .values(password_hash="malformed")
            )
        malformed = client.post(
            "/api/v1/auth/login",
            headers={"Origin": _ORIGIN, "Content-Type": "application/json"},
            json={"email": "login@example.test", "password": _PASSWORD},
        )
        assert malformed.status_code == 401
        assert malformed.json()["code"] == "invalid_credentials"

        _set_cookie(client, original_bearer)
        assert client.get("/api/v1/auth/me").status_code == 200

    with identity_database.session_factory() as database_session:
        assert database_session.scalar(select(func.count()).select_from(UserSession)) == 2


def test_me_returns_current_csrf_without_cookie_refresh_and_converges_session_failures(
    identity_database: DatabaseResources,
) -> None:
    client, _, clock = _test_client(identity_database)
    with client:
        registration = _register(client, email="me@example.test")
        bearer = registration.cookies.get(_COOKIE_NAME)
        assert bearer is not None
        clock.current = _NOW + timedelta(minutes=5)

        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.headers["cache-control"] == "no-store"
        assert "set-cookie" not in me.headers
        assert me.json()["csrf_token"] == registration.json()["csrf_token"]
        assert me.json()["user"]["updated_at"] == registration.json()["user"]["updated_at"]

        with identity_database.session_factory() as database_session:
            user_session = database_session.scalar(
                select(UserSession).where(
                    UserSession.token_hash == hash_session_token(decode_token(bearer))
                )
            )
            assert user_session is not None
            assert user_session.last_seen_at == clock.current
            user = database_session.get(User, user_session.user_id)
            assert user is not None
            assert user.updated_at == datetime.fromisoformat(me.json()["user"]["updated_at"])

        _set_cookie(client, None)
        missing = client.get("/api/v1/auth/me")
        _set_cookie(client, "malformed")
        malformed = client.get("/api/v1/auth/me")

        with identity_database.session_factory() as database_session, database_session.begin():
            database_session.execute(
                update(UserSession)
                .where(UserSession.token_hash == hash_session_token(decode_token(bearer)))
                .values(revoked_at=clock.current)
            )
        _set_cookie(client, bearer)
        revoked = client.get("/api/v1/auth/me")

        with identity_database.session_factory() as database_session, database_session.begin():
            database_session.execute(
                update(UserSession)
                .where(UserSession.token_hash == hash_session_token(decode_token(bearer)))
                .values(revoked_at=None)
            )
        clock.current = _NOW + timedelta(hours=12)
        expired = client.get("/api/v1/auth/me")

    for response in (missing, malformed, revoked, expired):
        assert response.status_code == 401
        assert response.json()["code"] == "authentication_required"
        assert response.json()["message"] == "Authentication required."
        assert "revoked" not in response.text
        assert "expired" not in response.text


def test_logout_is_session_bound_idempotent_and_deletes_only_after_success(
    identity_database: DatabaseResources,
) -> None:
    client, _, _ = _test_client(identity_database)
    with client:
        first = _register(client, email="logout@example.test")
        first_bearer = first.cookies.get(_COOKIE_NAME)
        first_csrf = first.json()["csrf_token"]
        assert first_bearer is not None

        second = client.post(
            "/api/v1/auth/login",
            headers={"Origin": _ORIGIN, "Content-Type": "application/json"},
            json={"email": "logout@example.test", "password": _PASSWORD},
        )
        second_bearer = second.cookies.get(_COOKIE_NAME)
        second_csrf = second.json()["csrf_token"]
        assert second_bearer is not None

        _set_cookie(client, first_bearer)
        missing_csrf = client.post("/api/v1/auth/logout", headers={"Origin": _ORIGIN})
        malformed_csrf = client.post(
            "/api/v1/auth/logout",
            headers={"Origin": _ORIGIN, "X-CSRF-Token": "malformed"},
        )
        other_session_csrf = client.post(
            "/api/v1/auth/logout",
            headers={"Origin": _ORIGIN, "X-CSRF-Token": second_csrf},
        )
        wrong_origin = client.post(
            "/api/v1/auth/logout",
            headers={"Origin": "https://wrong.example.test", "X-CSRF-Token": first_csrf},
        )

        for response in (missing_csrf, malformed_csrf, other_session_csrf, wrong_origin):
            assert response.status_code == 403
            assert "set-cookie" not in response.headers

        valid = client.post(
            "/api/v1/auth/logout",
            headers={"Origin": _ORIGIN, "X-CSRF-Token": first_csrf},
        )
        assert valid.status_code == 204
        assert valid.content == b""
        assert "Max-Age=0" in valid.headers["set-cookie"]

        _set_cookie(client, first_bearer)
        assert client.get("/api/v1/auth/me").status_code == 401
        repeated = client.post("/api/v1/auth/logout", headers={"Origin": _ORIGIN})
        assert repeated.status_code == 204
        assert "Max-Age=0" in repeated.headers["set-cookie"]

        _set_cookie(client, second_bearer)
        assert client.get("/api/v1/auth/me").status_code == 200

        _set_cookie(client, None)
        missing_session = client.post("/api/v1/auth/logout", headers={"Origin": _ORIGIN})
        assert missing_session.status_code == 204
        assert "Max-Age=0" in missing_session.headers["set-cookie"]

    with identity_database.session_factory() as database_session:
        first_row = database_session.scalar(
            select(UserSession).where(
                UserSession.token_hash == hash_session_token(decode_token(first_bearer))
            )
        )
        second_row = database_session.scalar(
            select(UserSession).where(
                UserSession.token_hash == hash_session_token(decode_token(second_bearer))
            )
        )
        assert first_row is not None and first_row.revoked_at is not None
        assert second_row is not None and second_row.revoked_at is None
