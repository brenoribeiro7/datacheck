from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(_StrictRequest):
    email: str
    password: str = Field(json_schema_extra={"writeOnly": True})


class LoginRequest(_StrictRequest):
    email: str
    password: str = Field(json_schema_extra={"writeOnly": True})


class UserResponse(BaseModel):
    id: UUID
    email: str
    created_at: AwareDatetime
    updated_at: AwareDatetime


class AuthenticatedSessionResponse(BaseModel):
    user: UserResponse
    csrf_token: str


class ValidationIssue(BaseModel):
    field: list[str | int]
    code: str
    message: str


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: list[ValidationIssue] | None = None
    trace_id: str
