from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from datacheck.analysis.schemas import (
    AnalysisDetail,
    AnalysisSourceSnapshot,
    AnalysisSummary,
    ValidationResultResponse,
    ViolationSampleResponse,
)
from datacheck.analysis.service import (
    AnalysisDetailReference,
    AnalysisRequiresRules,
    AnalysisService,
    AnalysisSummaryReference,
)
from datacheck.api.dependencies import (
    enforce_trusted_origin,
    get_analysis_service,
    require_authenticated_context,
    require_authenticated_mutation,
)
from datacheck.api.errors import ApiError
from datacheck.datasets.service import DatasetNotFound, DatasetNotReady
from datacheck.identity.schemas import ErrorResponse
from datacheck.identity.service import AuthenticatedContext


def _error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    return {status_code: {"model": ErrorResponse} for status_code in status_codes}


_CSRF_OPENAPI = {
    "parameters": [
        {
            "name": "X-CSRF-Token",
            "in": "header",
            "required": True,
            "description": (
                "Session-bound synchronizer token returned by authenticated session endpoints."
            ),
            "schema": {"type": "string"},
        }
    ]
}

router = APIRouter(prefix="/datasets/{dataset_id}/analyses", tags=["analyses"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=AnalysisDetail,
    responses=_error_responses(401, 403, 404, 409, 422, 500, 503),
    dependencies=[Depends(enforce_trusted_origin)],
    openapi_extra=_CSRF_OPENAPI,
)
def create_analysis(
    dataset_id: UUID,
    context: Annotated[AuthenticatedContext, Depends(require_authenticated_mutation)],
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
) -> AnalysisDetail:
    try:
        analysis = service.create_analysis(
            owner_id=context.user.user_id,
            dataset_id=dataset_id,
        )
    except DatasetNotFound:
        raise _not_found() from None
    except DatasetNotReady:
        raise ApiError(
            status_code=409,
            code="dataset_not_ready",
            message="Dataset requires a valid CSV upload before analysis.",
        ) from None
    except AnalysisRequiresRules:
        raise ApiError(
            status_code=409,
            code="analysis_requires_rules",
            message="Dataset requires at least one validation rule before analysis.",
        ) from None
    return _detail_response(analysis)


@router.get(
    "",
    response_model=list[AnalysisSummary],
    responses=_error_responses(401, 404, 422, 500, 503),
)
def list_analyses(
    dataset_id: UUID,
    context: Annotated[AuthenticatedContext, Depends(require_authenticated_context)],
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AnalysisSummary]:
    try:
        analyses = service.list_analyses(
            owner_id=context.user.user_id,
            dataset_id=dataset_id,
            limit=limit,
            offset=offset,
        )
    except DatasetNotFound:
        raise _not_found() from None
    return [_summary_response(analysis) for analysis in analyses]


@router.get(
    "/{analysis_id}",
    response_model=AnalysisDetail,
    responses=_error_responses(401, 404, 422, 500, 503),
)
def get_analysis(
    dataset_id: UUID,
    analysis_id: UUID,
    context: Annotated[AuthenticatedContext, Depends(require_authenticated_context)],
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
) -> AnalysisDetail:
    try:
        analysis = service.get_analysis(
            owner_id=context.user.user_id,
            dataset_id=dataset_id,
            analysis_id=analysis_id,
        )
    except DatasetNotFound:
        raise _not_found() from None
    return _detail_response(analysis)


def _summary_response(analysis: AnalysisSummaryReference) -> AnalysisSummary:
    return AnalysisSummary(
        id=analysis.analysis_id,
        dataset_id=analysis.dataset_id,
        quality_score=(None if analysis.quality_score is None else float(analysis.quality_score)),
        source_row_count=analysis.source_row_count,
        total_violation_count=analysis.total_violation_count,
        created_at=analysis.created_at,
    )


def _detail_response(analysis: AnalysisDetailReference) -> AnalysisDetail:
    summary = _summary_response(analysis)
    return AnalysisDetail(
        **summary.model_dump(),
        source=AnalysisSourceSnapshot(
            original_filename=analysis.source.original_filename,
            content_sha256=analysis.source.content_sha256.hex(),
            size_bytes=analysis.source.size_bytes,
            row_count=analysis.source.row_count,
            column_names=list(analysis.source.column_names),
            uploaded_at=analysis.source.uploaded_at,
        ),
        rule_results=[
            ValidationResultResponse(
                rule_position=result.rule_position,
                source_rule_id=result.source_rule_id,
                rule_type=result.rule_type,  # type: ignore[arg-type]
                target_column=result.target_column,
                configuration=result.configuration,
                evaluated_count=result.evaluated_count,
                passed_count=result.passed_count,
                violation_count=result.violation_count,
                skipped_count=result.skipped_count,
                violation_samples=[
                    ViolationSampleResponse(
                        row_number=sample.row_number,
                        value_preview=sample.value_preview,
                        truncated=sample.truncated,
                    )
                    for sample in result.violation_samples
                ],
            )
            for result in analysis.rule_results
        ],
    )


def _not_found() -> ApiError:
    return ApiError(status_code=404, code="not_found", message="Resource not found.")
