from typing import Annotated, cast

from fastapi import Depends, Request

from datacheck.api.errors import ApiError
from datacheck.api.security import cookie_policy, require_json_content_type, require_trusted_origin
from datacheck.core.settings import ApiSettings
from datacheck.identity.service import AuthenticatedContext, AuthenticationRequired, IdentityService


def get_api_settings(request: Request) -> ApiSettings:
    return cast(ApiSettings, request.app.state.api_settings)


def get_identity_service(request: Request) -> IdentityService:
    service = getattr(request.app.state, "identity_service", None)
    if service is None:
        raise RuntimeError("identity service is unavailable")
    return cast(IdentityService, service)


def enforce_trusted_origin(
    request: Request,
    settings: Annotated[ApiSettings, Depends(get_api_settings)],
) -> None:
    require_trusted_origin(request, settings)


def enforce_json_content_type(request: Request) -> None:
    require_json_content_type(request)


def require_authenticated_context(
    request: Request,
    settings: Annotated[ApiSettings, Depends(get_api_settings)],
    identity_service: Annotated[IdentityService, Depends(get_identity_service)],
) -> AuthenticatedContext:
    policy = cookie_policy(settings.environment)
    try:
        return identity_service.authenticate(request.cookies.get(policy.name))
    except AuthenticationRequired:
        raise ApiError(
            status_code=401,
            code="authentication_required",
            message="Authentication required.",
        ) from None
