from collections.abc import Sequence
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from datacheck.identity.schemas import ErrorResponse, ValidationIssue


class ApiError(Exception):
    """Carry a stable public API failure without internal diagnostic details."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Sequence[ValidationIssue] | None = None,
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = list(details) if details is not None else None


def ensure_trace_id(request: Request) -> str:
    trace_id = getattr(request.state, "trace_id", None)
    if not isinstance(trace_id, str):
        trace_id = uuid4().hex
        request.state.trace_id = trace_id
    return trace_id


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: Sequence[ValidationIssue] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        code=code,
        message=message,
        details=list(details) if details is not None else None,
        trace_id=ensure_trace_id(request),
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def policy_validation_error(*, field: str, code: str, message: str) -> ApiError:
    return ApiError(
        status_code=422,
        code="validation_error",
        message="Request validation failed.",
        details=[ValidationIssue(field=["body", field], code=code, message=message)],
    )


def _validation_issues(error: RequestValidationError) -> list[ValidationIssue]:
    messages = {
        "missing": "Field is required.",
        "extra_forbidden": "Extra fields are not permitted.",
        "string_type": "Value must be a string.",
    }
    issues: list[ValidationIssue] = []
    for item in error.errors():
        error_type = str(item.get("type", "invalid_value"))
        raw_location = item.get("loc", ())
        location = [part for part in raw_location if isinstance(part, (str, int))]
        issues.append(
            ValidationIssue(
                field=location,
                code=error_type,
                message=messages.get(error_type, "Invalid value."),
            )
        )
    return issues


def register_error_handlers(application: FastAPI) -> None:
    @application.exception_handler(ApiError)
    async def handle_api_error(request: Request, error: ApiError) -> JSONResponse:
        return error_response(
            request,
            status_code=error.status_code,
            code=error.code,
            message=error.message,
            details=error.details,
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        return error_response(
            request,
            status_code=422,
            code="validation_error",
            message="Request validation failed.",
            details=_validation_issues(error),
        )

    @application.exception_handler(SQLAlchemyError)
    async def handle_database_error(request: Request, _error: SQLAlchemyError) -> JSONResponse:
        return error_response(
            request,
            status_code=503,
            code="service_unavailable",
            message="Service temporarily unavailable.",
        )


def unexpected_error_response(request: Request) -> JSONResponse:
    return error_response(
        request,
        status_code=500,
        code="internal_error",
        message="Internal server error.",
    )
