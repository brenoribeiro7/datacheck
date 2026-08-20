import uuid
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.requests import Request
from starlette.responses import Response

from datacheck.api.security import (
    SESSION_MAX_AGE,
    cookie_policy,
    expire_session_cookie,
    parse_csrf_header,
    require_json_content_type,
    require_trusted_origin,
    set_session_cookie,
)
from datacheck.core.settings import ApiSettings
from datacheck.identity.service import SessionIssuance, UserReference
from datacheck.identity.tokens import encode_token
from datacheck.main import create_app

_NOW = datetime(2026, 4, 1, 12, tzinfo=UTC)
_ORIGIN = "http://localhost:3000"


def _settings() -> ApiSettings:
    return ApiSettings(
        environment="test",
        database_url=SecretStr("postgresql+psycopg://127.0.0.1/datacheck"),
        trusted_origins=(_ORIGIN,),
        dataset_storage_root=Path("/tmp/datacheck-test-datasets"),
    )


def _request(*headers: tuple[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/auth/logout",
            "raw_path": b"/api/v1/auth/logout",
            "query_string": b"",
            "root_path": "",
            "headers": [(name.lower().encode(), value.encode()) for name, value in headers],
            "client": ("127.0.0.1", 10000),
            "server": ("testserver", 80),
        }
    )


def _issuance() -> SessionIssuance:
    return SessionIssuance(
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


def test_origin_is_exact_and_referer_is_a_fail_closed_fallback() -> None:
    settings = _settings()

    require_trusted_origin(_request(("Origin", "HTTP://LOCALHOST:3000")), settings)
    require_trusted_origin(
        _request(("Referer", "http://localhost:3000/auth/login?next=%2F#fragment")), settings
    )

    for request in (
        _request(),
        _request(("Origin", "null")),
        _request(("Origin", "http://127.0.0.1:3000")),
        _request(("Origin", _ORIGIN), ("Origin", _ORIGIN)),
        _request(("Origin", "https://wrong.example.test"), ("Referer", f"{_ORIGIN}/")),
        _request(("Referer", "https://user@example.test/path")),
    ):
        with pytest.raises(Exception) as error:
            require_trusted_origin(request, settings)
        assert getattr(error.value, "code", None) == "invalid_origin"


@pytest.mark.parametrize(
    "content_type",
    [
        "application/json",
        "Application/JSON",
        "application/json; charset=utf-8",
        'application/json; Charset="UTF-8"',
    ],
)
def test_content_type_accepts_only_json_with_optional_utf8(content_type: str) -> None:
    require_json_content_type(_request(("Content-Type", content_type)))


@pytest.mark.parametrize(
    "headers",
    [
        (),
        (("Content-Type", "text/plain"),),
        (("Content-Type", "application/json; charset=latin-1"),),
        (("Content-Type", "application/json; profile=example"),),
        (("Content-Type", "application/json; charset=utf-8; profile=example"),),
        (("Content-Type", "application/json"), ("Content-Type", "application/json")),
    ],
)
def test_content_type_rejects_missing_invalid_or_extra_parameters(
    headers: tuple[tuple[str, str], ...],
) -> None:
    with pytest.raises(Exception) as error:
        require_json_content_type(_request(*headers))
    assert getattr(error.value, "code", None) == "unsupported_media_type"


def test_cookie_policies_and_explicit_deletion_attributes() -> None:
    issuance = _issuance()
    for environment, expected_name, secure in (
        ("production", "__Host-datacheck_session", True),
        ("development", "datacheck_session", False),
        ("test", "datacheck_session", False),
    ):
        policy = cookie_policy(environment)  # type: ignore[arg-type]
        assert policy.name == expected_name
        assert policy.secure is secure

        creation = Response()
        set_session_cookie(creation, policy=policy, issuance=issuance)
        created_header = creation.headers["set-cookie"]
        parsed_creation = SimpleCookie()
        parsed_creation.load(created_header)
        created = parsed_creation[expected_name]
        assert created.value == issuance.bearer_token
        assert created["max-age"] == str(SESSION_MAX_AGE)
        assert created["path"] == "/"
        assert created["httponly"] is True
        assert created["samesite"].lower() == "lax"
        assert created["domain"] == ""
        assert bool(created["secure"]) is secure
        assert created["expires"]

        deletion = Response()
        expire_session_cookie(deletion, policy=policy)
        deleted_header = deletion.headers["set-cookie"]
        parsed_deletion = SimpleCookie()
        parsed_deletion.load(deleted_header)
        deleted = parsed_deletion[expected_name]
        assert deleted.value == ""
        assert deleted["max-age"] == "0"
        assert deleted["path"] == "/"
        assert deleted["httponly"] is True
        assert deleted["samesite"].lower() == "lax"
        assert deleted["domain"] == ""
        assert bool(deleted["secure"]) is secure
        assert "1970" in deleted["expires"]


def test_csrf_transport_parser_requires_one_canonical_token() -> None:
    encoded = encode_token(b"c" * 32)
    assert parse_csrf_header(_request(("X-CSRF-Token", encoded))) == b"c" * 32
    assert parse_csrf_header(_request()) is None
    assert parse_csrf_header(_request(("X-CSRF-Token", "malformed"))) is None
    assert parse_csrf_header(_request(("X-CSRF-Token", encoded), ("X-CSRF-Token", encoded))) is None


def test_cors_preflight_is_explicit_and_never_wildcarded() -> None:
    application = create_app(settings=_settings(), database_probe=lambda: None)
    with TestClient(application) as client:
        response = client.options(
            "/api/v1/auth/logout",
            headers={
                "Origin": _ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type, X-CSRF-Token",
            },
        )
        rejected = client.options(
            "/api/v1/auth/logout",
            headers={
                "Origin": "https://wrong.example.test",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == _ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "content-type" in response.headers["access-control-allow-headers"].lower()
    assert "x-csrf-token" in response.headers["access-control-allow-headers"].lower()
    assert response.headers["access-control-max-age"] == "600"
    assert response.headers["access-control-allow-origin"] != "*"
    assert "x-trace-id" in response.headers
    assert "access-control-allow-origin" not in rejected.headers
