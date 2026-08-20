from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit

from fastapi import Request, Response

from datacheck.api.errors import ApiError
from datacheck.core.settings import ApiSettings, Environment, canonicalize_origin
from datacheck.identity.service import SessionIssuance
from datacheck.identity.tokens import TokenEncodingError, decode_token

SESSION_MAX_AGE = 43_200


@dataclass(frozen=True, slots=True)
class CookiePolicy:
    name: str
    secure: bool
    httponly: bool = True
    samesite: Literal["lax"] = "lax"
    path: str = "/"


def cookie_policy(environment: Environment) -> CookiePolicy:
    if environment == "production":
        return CookiePolicy(name="__Host-datacheck_session", secure=True)
    return CookiePolicy(name="datacheck_session", secure=False)


def set_session_cookie(
    response: Response,
    *,
    policy: CookiePolicy,
    issuance: SessionIssuance,
) -> None:
    response.set_cookie(
        key=policy.name,
        value=issuance.bearer_token,
        max_age=SESSION_MAX_AGE,
        expires=issuance.absolute_expires_at,
        path=policy.path,
        secure=policy.secure,
        httponly=policy.httponly,
        samesite=policy.samesite,
    )


def expire_session_cookie(response: Response, *, policy: CookiePolicy) -> None:
    response.set_cookie(
        key=policy.name,
        value="",
        max_age=0,
        expires=datetime(1970, 1, 1, tzinfo=UTC),
        path=policy.path,
        secure=policy.secure,
        httponly=policy.httponly,
        samesite=policy.samesite,
    )


def require_trusted_origin(request: Request, settings: ApiSettings) -> None:
    origin_values = request.headers.getlist("origin")
    if origin_values:
        if len(origin_values) != 1:
            raise _invalid_origin()
        try:
            origin = canonicalize_origin(origin_values[0])
        except (TypeError, ValueError):
            raise _invalid_origin() from None
    else:
        referer_values = request.headers.getlist("referer")
        if len(referer_values) != 1:
            raise _invalid_origin()
        try:
            origin = _origin_from_referer(referer_values[0])
        except (TypeError, ValueError):
            raise _invalid_origin() from None

    if origin not in settings.trusted_origins:
        raise _invalid_origin()


def require_json_content_type(request: Request) -> None:
    values = request.headers.getlist("content-type")
    if len(values) != 1:
        raise _unsupported_media_type()
    sections = [section.strip() for section in values[0].split(";")]
    if not sections or sections[0].lower() != "application/json":
        raise _unsupported_media_type()
    parameters = sections[1:]
    if not parameters:
        return
    if len(parameters) != 1 or "=" not in parameters[0]:
        raise _unsupported_media_type()
    name, value = (part.strip() for part in parameters[0].split("=", 1))
    charset = value.strip('"').lower()
    if name.lower() != "charset" or charset != "utf-8":
        raise _unsupported_media_type()


def parse_csrf_header(request: Request) -> bytes | None:
    values = request.headers.getlist("x-csrf-token")
    if len(values) != 1:
        return None
    try:
        return decode_token(values[0])
    except (TokenEncodingError, TypeError):
        return None


def _origin_from_referer(value: str) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise ValueError("invalid Referer")
    parsed = urlsplit(value)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("invalid Referer")
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("invalid Referer") from None
    hostname = parsed.hostname
    if hostname is None:
        raise ValueError("invalid Referer")
    display_hostname = f"[{hostname}]" if ":" in hostname else hostname
    candidate = f"{parsed.scheme}://{display_hostname}{f':{port}' if port is not None else ''}"
    return canonicalize_origin(candidate)


def _invalid_origin() -> ApiError:
    return ApiError(
        status_code=403,
        code="invalid_origin",
        message="Request origin is not trusted.",
    )


def _unsupported_media_type() -> ApiError:
    return ApiError(
        status_code=415,
        code="unsupported_media_type",
        message="Content-Type must be application/json with UTF-8 encoding.",
    )
