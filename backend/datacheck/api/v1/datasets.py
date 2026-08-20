from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHttpException

from datacheck.api.dependencies import (
    enforce_json_content_type,
    enforce_multipart_content_type,
    enforce_trusted_origin,
    get_dataset_service,
    require_authenticated_context,
    require_authenticated_mutation,
)
from datacheck.api.errors import ApiError
from datacheck.datasets.csv import CsvStructureError
from datacheck.datasets.policies import DatasetPolicyError
from datacheck.datasets.schemas import (
    DatasetCreateRequest,
    DatasetDetail,
    DatasetSummary,
    RuleCreateRequest,
    UploadMetadataResponse,
    ValidationRuleResponse,
    canonical_rule_configuration,
)
from datacheck.datasets.service import (
    DatasetNotFound,
    DatasetNotReady,
    DatasetReference,
    DatasetService,
    DuplicateRule,
    IncompatibleUpload,
    UnknownColumn,
    ValidationRuleReference,
)
from datacheck.datasets.storage import FileTooLarge
from datacheck.identity.schemas import ErrorResponse
from datacheck.identity.service import AuthenticatedContext


def _error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    return {status_code: {"model": ErrorResponse} for status_code in status_codes}


_CSRF_PARAMETER = {
    "name": "X-CSRF-Token",
    "in": "header",
    "required": True,
    "description": "Session-bound synchronizer token returned by authenticated session endpoints.",
    "schema": {"type": "string"},
}
_CSRF_OPENAPI = {"parameters": [_CSRF_PARAMETER]}
_UPLOAD_OPENAPI = {
    "parameters": [_CSRF_PARAMETER],
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["file"],
                    "properties": {"file": {"type": "string", "format": "binary"}},
                }
            }
        },
    },
}

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=DatasetDetail,
    responses=_error_responses(401, 403, 415, 422, 500, 503),
    dependencies=[Depends(enforce_trusted_origin), Depends(enforce_json_content_type)],
    openapi_extra=_CSRF_OPENAPI,
)
def create_dataset(
    payload: DatasetCreateRequest,
    context: Annotated[AuthenticatedContext, Depends(require_authenticated_mutation)],
    service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> DatasetDetail:
    try:
        dataset = service.create_dataset(owner_id=context.user.user_id, name=payload.name)
    except DatasetPolicyError:
        raise _validation_error(
            "name", "invalid_dataset_name", "Dataset name is invalid."
        ) from None
    return _dataset_detail(dataset)


@router.get(
    "",
    response_model=list[DatasetSummary],
    responses=_error_responses(401, 422, 500, 503),
)
def list_datasets(
    context: Annotated[AuthenticatedContext, Depends(require_authenticated_context)],
    service: Annotated[DatasetService, Depends(get_dataset_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DatasetSummary]:
    return [
        _dataset_summary(dataset)
        for dataset in service.list_datasets(
            owner_id=context.user.user_id, limit=limit, offset=offset
        )
    ]


@router.get(
    "/{dataset_id}",
    response_model=DatasetDetail,
    responses=_error_responses(401, 404, 422, 500, 503),
)
def get_dataset(
    dataset_id: UUID,
    context: Annotated[AuthenticatedContext, Depends(require_authenticated_context)],
    service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> DatasetDetail:
    try:
        dataset = service.get_dataset(owner_id=context.user.user_id, dataset_id=dataset_id)
    except DatasetNotFound:
        raise _not_found() from None
    return _dataset_detail(dataset)


@router.post(
    "/{dataset_id}/upload",
    response_model=DatasetDetail,
    responses=_error_responses(400, 401, 403, 404, 409, 413, 415, 422, 500, 503),
    dependencies=[Depends(enforce_trusted_origin), Depends(enforce_multipart_content_type)],
    openapi_extra=_UPLOAD_OPENAPI,
)
async def upload_csv(
    dataset_id: UUID,
    request: Request,
    context: Annotated[AuthenticatedContext, Depends(require_authenticated_mutation)],
    service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> DatasetDetail:
    try:
        async with request.form(max_files=2, max_fields=1) as form:
            parts = form.multi_items()
            if len(parts) != 1 or parts[0][0] != "file" or not isinstance(parts[0][1], UploadFile):
                raise _invalid_multipart()
            upload = parts[0][1]
            dataset = await run_in_threadpool(
                service.upload_csv,
                owner_id=context.user.user_id,
                dataset_id=dataset_id,
                original_filename=upload.filename,
                source=upload.file,
            )
    except StarletteHttpException:
        raise _invalid_multipart() from None
    except DatasetNotFound:
        raise _not_found() from None
    except DatasetPolicyError as error:
        field = "filename" if error.code == "invalid_filename" else "file"
        raise _validation_error(field, error.code, "Uploaded file is invalid.") from None
    except CsvStructureError as error:
        raise _validation_error("file", error.code, "CSV structure is invalid.") from None
    except FileTooLarge:
        raise ApiError(
            status_code=413,
            code="upload_too_large",
            message="Upload exceeds the accepted size limit.",
        ) from None
    except IncompatibleUpload:
        raise ApiError(
            status_code=409,
            code="upload_conflicts_with_rules",
            message="Upload is incompatible with configured validation rules.",
        ) from None
    return _dataset_detail(dataset)


@router.post(
    "/{dataset_id}/rules",
    status_code=status.HTTP_201_CREATED,
    response_model=ValidationRuleResponse,
    responses=_error_responses(401, 403, 404, 409, 415, 422, 500, 503),
    dependencies=[Depends(enforce_trusted_origin), Depends(enforce_json_content_type)],
    openapi_extra=_CSRF_OPENAPI,
)
def create_rule(
    dataset_id: UUID,
    payload: RuleCreateRequest,
    context: Annotated[AuthenticatedContext, Depends(require_authenticated_mutation)],
    service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> ValidationRuleResponse:
    try:
        rule = service.create_rule(
            owner_id=context.user.user_id,
            dataset_id=dataset_id,
            rule_type=payload.type,
            target_column=payload.target_column,
            configuration=canonical_rule_configuration(payload),
        )
    except DatasetNotFound:
        raise _not_found() from None
    except DatasetNotReady:
        raise ApiError(
            status_code=409,
            code="dataset_not_ready",
            message="Dataset requires a valid CSV upload before configuring rules.",
        ) from None
    except UnknownColumn:
        raise _validation_error(
            "target_column", "unknown_column", "Target column does not exist in the dataset."
        ) from None
    except DuplicateRule:
        raise ApiError(
            status_code=409,
            code="duplicate_rule",
            message="An identical validation rule already exists.",
        ) from None
    except DatasetPolicyError:
        raise _validation_error(
            "target_column", "invalid_target_column", "Target column is invalid."
        ) from None
    return _rule_response(rule)


@router.get(
    "/{dataset_id}/rules",
    response_model=list[ValidationRuleResponse],
    responses=_error_responses(401, 404, 422, 500, 503),
)
def list_rules(
    dataset_id: UUID,
    context: Annotated[AuthenticatedContext, Depends(require_authenticated_context)],
    service: Annotated[DatasetService, Depends(get_dataset_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ValidationRuleResponse]:
    try:
        rows = service.list_rules(
            owner_id=context.user.user_id,
            dataset_id=dataset_id,
            limit=limit,
            offset=offset,
        )
    except DatasetNotFound:
        raise _not_found() from None
    return [_rule_response(rule) for rule in rows]


@router.delete(
    "/{dataset_id}/rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_error_responses(401, 403, 404, 500, 503),
    dependencies=[Depends(enforce_trusted_origin)],
    openapi_extra=_CSRF_OPENAPI,
)
def delete_rule(
    dataset_id: UUID,
    rule_id: UUID,
    context: Annotated[AuthenticatedContext, Depends(require_authenticated_mutation)],
    service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> None:
    try:
        service.delete_rule(
            owner_id=context.user.user_id,
            dataset_id=dataset_id,
            rule_id=rule_id,
        )
    except DatasetNotFound:
        raise _not_found() from None


def _dataset_summary(dataset: DatasetReference) -> DatasetSummary:
    return DatasetSummary(
        id=dataset.dataset_id,
        name=dataset.name,
        has_upload=dataset.upload is not None,
        created_at=dataset.created_at,
        updated_at=dataset.updated_at,
    )


def _dataset_detail(dataset: DatasetReference) -> DatasetDetail:
    summary = _dataset_summary(dataset)
    upload = dataset.upload
    return DatasetDetail(
        **summary.model_dump(),
        upload=(
            None
            if upload is None
            else UploadMetadataResponse(
                original_filename=upload.original_filename,
                size_bytes=upload.size_bytes,
                row_count=upload.row_count,
                columns=list(upload.columns),
                sha256=upload.content_sha256.hex(),
                uploaded_at=upload.uploaded_at,
            )
        ),
    )


def _rule_response(rule: ValidationRuleReference) -> ValidationRuleResponse:
    return ValidationRuleResponse(
        id=rule.rule_id,
        dataset_id=rule.dataset_id,
        type=rule.rule_type,  # type: ignore[arg-type]
        target_column=rule.target_column,
        configuration=rule.configuration,
        created_at=rule.created_at,
    )


def _not_found() -> ApiError:
    return ApiError(status_code=404, code="not_found", message="Resource not found.")


def _invalid_multipart() -> ApiError:
    return ApiError(
        status_code=400,
        code="invalid_multipart",
        message="Upload must contain exactly one file part.",
    )


def _validation_error(field: str, code: str, message: str) -> ApiError:
    from datacheck.identity.schemas import ValidationIssue

    return ApiError(
        status_code=422,
        code="validation_error",
        message="Request validation failed.",
        details=[ValidationIssue(field=["body", field], code=code, message=message)],
    )
