from dataclasses import dataclass
from typing import Literal
from uuid import UUID

VIOLATION_SAMPLE_LIMIT = 20
VALUE_PREVIEW_LIMIT = 128

type ExpectedType = Literal["string", "integer", "number", "boolean", "date", "datetime"]


class ValidationInputError(ValueError):
    """Indicate that the engine received an invalid table or rule specification."""


@dataclass(frozen=True, slots=True)
class RequiredRuleSpec:
    rule_id: UUID
    target_column: str


@dataclass(frozen=True, slots=True)
class UniqueRuleSpec:
    rule_id: UUID
    target_column: str


@dataclass(frozen=True, slots=True)
class TypeRuleSpec:
    rule_id: UUID
    target_column: str
    expected_type: ExpectedType


@dataclass(frozen=True, slots=True)
class RangeRuleSpec:
    rule_id: UUID
    target_column: str
    minimum: float | None = None
    maximum: float | None = None


@dataclass(frozen=True, slots=True)
class RegexRuleSpec:
    rule_id: UUID
    target_column: str
    pattern: str


type ValidationRuleSpec = (
    RequiredRuleSpec | UniqueRuleSpec | TypeRuleSpec | RangeRuleSpec | RegexRuleSpec
)


@dataclass(frozen=True, slots=True)
class ViolationSample:
    row_number: int
    value_preview: str | None
    truncated: bool


@dataclass(frozen=True, slots=True)
class RuleValidationResult:
    rule: ValidationRuleSpec
    evaluated_count: int
    passed_count: int
    violation_count: int
    skipped_count: int
    violation_samples: tuple[ViolationSample, ...]


@dataclass(frozen=True, slots=True)
class ValidationEngineResult:
    total_rows: int
    rule_results: tuple[RuleValidationResult, ...]
