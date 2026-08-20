from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    field_validator,
    model_validator,
)

from datacheck.datasets.policies import DatasetPolicyError, validate_polars_regex


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetCreateRequest(_StrictModel):
    name: str


class UploadMetadataResponse(BaseModel):
    original_filename: str
    size_bytes: int
    row_count: int
    columns: list[str]
    sha256: str
    uploaded_at: AwareDatetime


class DatasetSummary(BaseModel):
    id: UUID
    name: str
    has_upload: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime


class DatasetDetail(DatasetSummary):
    upload: UploadMetadataResponse | None


class EmptyRuleConfiguration(_StrictModel):
    pass


class TypeRuleConfiguration(_StrictModel):
    expected_type: Literal["string", "integer", "number", "boolean", "date", "datetime"]


class RangeRuleConfiguration(_StrictModel):
    minimum: FiniteFloat | None = None
    maximum: FiniteFloat | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> "RangeRuleConfiguration":
        if self.minimum is None and self.maximum is None:
            raise ValueError("at least one range boundary is required")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        return self


class RegexRuleConfiguration(_StrictModel):
    pattern: str = Field(min_length=1, max_length=256)

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, value: str) -> str:
        try:
            return validate_polars_regex(value)
        except DatasetPolicyError:
            raise ValueError("pattern is not valid for the supported regex dialect") from None


class _RuleRequestBase(_StrictModel):
    target_column: str


class RequiredRuleRequest(_RuleRequestBase):
    type: Literal["required"]
    configuration: EmptyRuleConfiguration


class UniqueRuleRequest(_RuleRequestBase):
    type: Literal["unique"]
    configuration: EmptyRuleConfiguration


class TypeRuleRequest(_RuleRequestBase):
    type: Literal["type"]
    configuration: TypeRuleConfiguration


class RangeRuleRequest(_RuleRequestBase):
    type: Literal["range"]
    configuration: RangeRuleConfiguration


class RegexRuleRequest(_RuleRequestBase):
    type: Literal["regex"]
    configuration: RegexRuleConfiguration


type RuleCreateRequest = Annotated[
    RequiredRuleRequest | UniqueRuleRequest | TypeRuleRequest | RangeRuleRequest | RegexRuleRequest,
    Field(discriminator="type"),
]


class ValidationRuleResponse(BaseModel):
    id: UUID
    dataset_id: UUID
    type: Literal["required", "unique", "type", "range", "regex"]
    target_column: str
    configuration: dict[str, object]
    created_at: AwareDatetime


def canonical_rule_configuration(payload: RuleCreateRequest) -> dict[str, object]:
    if isinstance(payload.configuration, EmptyRuleConfiguration):
        return {}
    return payload.configuration.model_dump(mode="json")
