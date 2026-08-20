import uuid
from dataclasses import dataclass
from io import BytesIO

import polars as pl
from pydantic import ValidationError

from datacheck.datasets.schemas import (
    EmptyRuleConfiguration,
    RangeRuleConfiguration,
    RegexRuleConfiguration,
    TypeRuleConfiguration,
)
from datacheck.validation import (
    RangeRuleSpec,
    RegexRuleSpec,
    RequiredRuleSpec,
    TypeRuleSpec,
    UniqueRuleSpec,
    ValidationRuleSpec,
)


class AnalysisDataIntegrityError(RuntimeError):
    """Indicate that persisted dataset state cannot be analyzed safely."""


@dataclass(frozen=True, slots=True)
class PersistedRuleSnapshot:
    rule_id: uuid.UUID
    rule_type: str
    target_column: str
    configuration: dict[str, object]


@dataclass(frozen=True, slots=True)
class AdaptedRule:
    rule_id: uuid.UUID
    rule_type: str
    target_column: str
    configuration: dict[str, object]
    spec: ValidationRuleSpec


def load_textual_csv(
    content: bytes,
    *,
    expected_columns: tuple[str, ...],
    expected_row_count: int,
) -> pl.DataFrame:
    try:
        frame = pl.read_csv(
            BytesIO(content),
            has_header=True,
            separator=",",
            infer_schema=False,
            encoding="utf8",
            try_parse_dates=False,
            empty_string_is_null=False,
            null_values=None,
            ignore_errors=False,
            truncate_ragged_lines=False,
            raise_if_empty=True,
        )
    except (pl.exceptions.PolarsError, UnicodeError, ValueError):
        raise AnalysisDataIntegrityError("active CSV cannot be parsed") from None

    if tuple(frame.columns) != expected_columns:
        raise AnalysisDataIntegrityError("active CSV columns do not match persisted metadata")
    if frame.height != expected_row_count:
        raise AnalysisDataIntegrityError("active CSV row count does not match persisted metadata")
    if any(dtype != pl.String for dtype in frame.schema.values()):
        raise AnalysisDataIntegrityError("active CSV is not a textual table")
    return frame


def adapt_rules(rules: tuple[PersistedRuleSnapshot, ...]) -> tuple[AdaptedRule, ...]:
    try:
        return tuple(_adapt_rule(rule) for rule in rules)
    except (ValidationError, TypeError, ValueError):
        raise AnalysisDataIntegrityError("persisted validation rule is invalid") from None


def _adapt_rule(rule: PersistedRuleSnapshot) -> AdaptedRule:
    if rule.rule_type == "required":
        configuration = EmptyRuleConfiguration.model_validate(rule.configuration).model_dump(
            mode="json"
        )
        spec: ValidationRuleSpec = RequiredRuleSpec(rule.rule_id, rule.target_column)
    elif rule.rule_type == "unique":
        configuration = EmptyRuleConfiguration.model_validate(rule.configuration).model_dump(
            mode="json"
        )
        spec = UniqueRuleSpec(rule.rule_id, rule.target_column)
    elif rule.rule_type == "type":
        parsed = TypeRuleConfiguration.model_validate(rule.configuration)
        configuration = parsed.model_dump(mode="json")
        spec = TypeRuleSpec(rule.rule_id, rule.target_column, parsed.expected_type)
    elif rule.rule_type == "range":
        parsed_range = RangeRuleConfiguration.model_validate(rule.configuration)
        configuration = parsed_range.model_dump(mode="json")
        spec = RangeRuleSpec(
            rule.rule_id,
            rule.target_column,
            minimum=parsed_range.minimum,
            maximum=parsed_range.maximum,
        )
    elif rule.rule_type == "regex":
        parsed_regex = RegexRuleConfiguration.model_validate(rule.configuration)
        configuration = parsed_regex.model_dump(mode="json")
        spec = RegexRuleSpec(rule.rule_id, rule.target_column, parsed_regex.pattern)
    else:
        raise AnalysisDataIntegrityError("persisted validation rule type is unsupported")

    return AdaptedRule(
        rule_id=rule.rule_id,
        rule_type=rule.rule_type,
        target_column=rule.target_column,
        configuration=configuration,
        spec=spec,
    )
