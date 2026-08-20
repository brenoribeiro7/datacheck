from typing import Annotated, cast

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyCookie

from datacheck.api.errors import ApiError
from datacheck.api.security import (
    cookie_policy,
    parse_csrf_header,
    require_json_content_type,
    require_multipart_content_type,
    require_trusted_origin,
)
from datacheck.core.settings import ApiSettings
from datacheck.datasets.service import DatasetService
from datacheck.identity.service import AuthenticatedContext, AuthenticationRequired, IdentityService
from datacheck.identity.tokens import csrf_tokens_match

_development_session_cookie = APIKeyCookie(
    name="datacheck_session",
    scheme_name="DevelopmentSessionCookie",
    description="HttpOnly session cookie used in development and test environments.",
    auto_error=False,
)
_production_session_cookie = APIKeyCookie(
    name="__Host-datacheck_session",
    scheme_name="ProductionSessionCookie",
    description="Secure __Host- session cookie used in production.",
    auto_error=False,
)


def get_api_settings(request: Request) -> ApiSettings:
    return cast(ApiSettings, request.app.state.api_settings)


def get_identity_service(request: Request) -> IdentityService:
    service = getattr(request.app.state, "identity_service", None)
    if service is None:
        raise RuntimeError("identity service is unavailable")
    return cast(IdentityService, service)


def get_dataset_service(request: Request) -> DatasetService:
    service = getattr(request.app.state, "dataset_service", None)
    if service is None:
        raise RuntimeError("dataset service is unavailable")
    return cast(DatasetService, service)


def enforce_trusted_origin(
    request: Request,
    settings: Annotated[ApiSettings, Depends(get_api_settings)],
) -> None:
    require_trusted_origin(request, settings)


def enforce_json_content_type(request: Request) -> None:
    require_json_content_type(request)


def enforce_multipart_content_type(request: Request) -> None:
    require_multipart_content_type(request)


def get_session_cookie(
    settings: Annotated[ApiSettings, Depends(get_api_settings)],
    development_cookie: Annotated[str | None, Security(_development_session_cookie)],
    production_cookie: Annotated[str | None, Security(_production_session_cookie)],
) -> str | None:
    """Select the documented cookie name that belongs to the active environment."""
    if cookie_policy(settings.environment).secure:
        return production_cookie
    return development_cookie


def get_csrf_token(
    request: Request,
) -> bytes | None:
    """Parse the CSRF header while preserving duplicate-header rejection."""
    return parse_csrf_header(request)


def require_authenticated_context(
    encoded_bearer: Annotated[str | None, Depends(get_session_cookie)],
    identity_service: Annotated[IdentityService, Depends(get_identity_service)],
) -> AuthenticatedContext:
    try:
        return identity_service.authenticate(encoded_bearer)
    except AuthenticationRequired:
        raise ApiError(
            status_code=401,
            code="authentication_required",
            message="Authentication required.",
        ) from None


def require_authenticated_mutation(
    context: Annotated[AuthenticatedContext, Depends(require_authenticated_context)],
    supplied_csrf_token: Annotated[bytes | None, Depends(get_csrf_token)],
) -> AuthenticatedContext:
    if supplied_csrf_token is None or not csrf_tokens_match(
        context.csrf_token, supplied_csrf_token
    ):
        raise ApiError(
            status_code=403,
            code="invalid_csrf_token",
            message="CSRF token is invalid.",
        )
    return context
