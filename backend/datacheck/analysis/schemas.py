from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict


class _ResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisSummary(_ResponseModel):
    id: UUID
    dataset_id: UUID
    quality_score: float | None
    source_row_count: int
    total_violation_count: int
    created_at: AwareDatetime


class AnalysisSourceSnapshot(_ResponseModel):
    original_filename: str
    content_sha256: str
    size_bytes: int
    row_count: int
    column_names: list[str]
    uploaded_at: AwareDatetime


class ViolationSampleResponse(_ResponseModel):
    row_number: int
    value_preview: str | None
    truncated: bool


class ValidationResultResponse(_ResponseModel):
    rule_position: int
    source_rule_id: UUID
    rule_type: Literal["required", "unique", "type", "range", "regex"]
    target_column: str
    configuration: dict[str, object]
    evaluated_count: int
    passed_count: int
    violation_count: int
    skipped_count: int
    violation_samples: list[ViolationSampleResponse]


class AnalysisDetail(AnalysisSummary):
    source: AnalysisSourceSnapshot
    rule_results: list[ValidationResultResponse]
