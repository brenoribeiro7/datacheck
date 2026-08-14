from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status

from datacheck.api.dependencies import (
    enforce_json_content_type,
    enforce_trusted_origin,
    get_api_settings,
    get_identity_service,
    require_authenticated_context,
)
from datacheck.api.errors import ApiError, policy_validation_error
from datacheck.api.security import (
    cookie_policy,
    expire_session_cookie,
    parse_csrf_header,
    set_session_cookie,
)
from datacheck.core.settings import ApiSettings
from datacheck.identity.email import EmailPolicyError
from datacheck.identity.passwords import PasswordPolicyError
from datacheck.identity.schemas import (
    AuthenticatedSessionResponse,
    ErrorResponse,
    LoginRequest,
    RegisterRequest,
    UserResponse,
)
from datacheck.identity.service import (
    AuthenticatedContext,
    DuplicateIdentity,
    IdentityService,
    InvalidCredentials,
    InvalidCsrf,
    SessionIssuance,
    UserReference,
)
from datacheck.identity.tokens import encode_token

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
    status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {"model": ErrorResponse},
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
}

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=AuthenticatedSessionResponse,
    responses=_ERROR_RESPONSES,
    dependencies=[Depends(enforce_trusted_origin), Depends(enforce_json_content_type)],
)
def register(
    payload: RegisterRequest,
    response: Response,
    settings: Annotated[ApiSettings, Depends(get_api_settings)],
    identity_service: Annotated[IdentityService, Depends(get_identity_service)],
) -> AuthenticatedSessionResponse:
    try:
        issuance = identity_service.register(email=payload.email, password=payload.password)
    except EmailPolicyError:
        raise policy_validation_error(
            field="email",
            code="invalid_email",
            message="Email does not meet the accepted policy.",
        ) from None
    except PasswordPolicyError:
        raise policy_validation_error(
            field="password",
            code="invalid_password",
            message="Password does not meet the accepted policy.",
        ) from None
    except DuplicateIdentity:
        raise ApiError(
            status_code=409,
            code="email_already_registered",
            message="Email is already registered.",
        ) from None

    set_session_cookie(response, policy=cookie_policy(settings.environment), issuance=issuance)
    response.headers["Cache-Control"] = "no-store"
    return _issuance_response(issuance)


@router.post(
    "/login",
    response_model=AuthenticatedSessionResponse,
    responses=_ERROR_RESPONSES,
    dependencies=[Depends(enforce_trusted_origin), Depends(enforce_json_content_type)],
)
def login(
    payload: LoginRequest,
    response: Response,
    settings: Annotated[ApiSettings, Depends(get_api_settings)],
    identity_service: Annotated[IdentityService, Depends(get_identity_service)],
) -> AuthenticatedSessionResponse:
    try:
        issuance = identity_service.login(email=payload.email, password=payload.password)
    except PasswordPolicyError:
        raise policy_validation_error(
            field="password",
            code="invalid_password",
            message="Password does not meet the accepted policy.",
        ) from None
    except InvalidCredentials:
        raise ApiError(
            status_code=401,
            code="invalid_credentials",
            message="Invalid email or password.",
        ) from None

    set_session_cookie(response, policy=cookie_policy(settings.environment), issuance=issuance)
    response.headers["Cache-Control"] = "no-store"
    return _issuance_response(issuance)


@router.get(
    "/me",
    response_model=AuthenticatedSessionResponse,
    responses=_ERROR_RESPONSES,
)
def me(
    response: Response,
    context: Annotated[AuthenticatedContext, Depends(require_authenticated_context)],
) -> AuthenticatedSessionResponse:
    response.headers["Cache-Control"] = "no-store"
    return AuthenticatedSessionResponse(
        user=_user_response(context.user),
        csrf_token=encode_token(context.csrf_token),
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_ERROR_RESPONSES,
    dependencies=[Depends(enforce_trusted_origin)],
)
def logout(
    request: Request,
    response: Response,
    settings: Annotated[ApiSettings, Depends(get_api_settings)],
    identity_service: Annotated[IdentityService, Depends(get_identity_service)],
) -> None:
    policy = cookie_policy(settings.environment)
    try:
        identity_service.logout(
            encoded_bearer=request.cookies.get(policy.name),
            supplied_csrf_token=parse_csrf_header(request),
        )
    except InvalidCsrf:
        raise ApiError(
            status_code=403,
            code="invalid_csrf_token",
            message="CSRF token is invalid.",
        ) from None

    expire_session_cookie(response, policy=policy)
    response.headers["Cache-Control"] = "no-store"


def _issuance_response(issuance: SessionIssuance) -> AuthenticatedSessionResponse:
    return AuthenticatedSessionResponse(
        user=_user_response(issuance.user),
        csrf_token=issuance.csrf_token,
    )


def _user_response(user: UserReference) -> UserResponse:
    return UserResponse(
        id=user.user_id,
        email=user.email,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )
