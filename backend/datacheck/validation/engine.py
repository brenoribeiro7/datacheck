import math
from collections.abc import Sequence
from typing import cast
from uuid import UUID

import polars as pl

from datacheck.validation.models import (
    RangeRuleSpec,
    RegexRuleSpec,
    RequiredRuleSpec,
    TypeRuleSpec,
    UniqueRuleSpec,
    ValidationEngineResult,
    ValidationInputError,
    ValidationRuleSpec,
)
from datacheck.validation.rules import evaluate_rule, validate_regex_pattern

_EXPECTED_TYPES = frozenset({"string", "integer", "number", "boolean", "date", "datetime"})
_RULE_TYPES = (RequiredRuleSpec, UniqueRuleSpec, TypeRuleSpec, RangeRuleSpec, RegexRuleSpec)


def validate(
    data: pl.DataFrame,
    rules: Sequence[ValidationRuleSpec],
) -> ValidationEngineResult:
    """Evaluate an ordered rule sequence against an in-memory textual table."""
    if not isinstance(data, pl.DataFrame):
        raise ValidationInputError("data must be a Polars DataFrame")

    ordered_rules = tuple(rules)
    _validate_inputs(data, ordered_rules)
    results = []
    for rule in ordered_rules:
        values = cast(list[str | None], data.get_column(rule.target_column).to_list())
        results.append(evaluate_rule(values, rule))
    return ValidationEngineResult(total_rows=data.height, rule_results=tuple(results))


def _validate_inputs(data: pl.DataFrame, rules: tuple[ValidationRuleSpec, ...]) -> None:
    seen_rule_ids: set[UUID] = set()
    for rule in rules:
        if not isinstance(rule, _RULE_TYPES):
            raise ValidationInputError("unsupported validation rule")
        if not isinstance(rule.rule_id, UUID):
            raise ValidationInputError("rule ID must be a UUID")
        if rule.rule_id in seen_rule_ids:
            raise ValidationInputError("rule IDs must be unique")
        seen_rule_ids.add(rule.rule_id)

        if not isinstance(rule.target_column, str) or not rule.target_column:
            raise ValidationInputError("target column must be a non-empty string")
        if rule.target_column not in data.columns:
            raise ValidationInputError("target column does not exist")
        if data.schema[rule.target_column] != pl.String:
            raise ValidationInputError("target column must use the Polars String dtype")

        if isinstance(rule, TypeRuleSpec):
            if not isinstance(rule.expected_type, str) or rule.expected_type not in _EXPECTED_TYPES:
                raise ValidationInputError("expected type is unsupported")
        if isinstance(rule, RangeRuleSpec):
            _validate_range(rule)
        if isinstance(rule, RegexRuleSpec):
            validate_regex_pattern(rule.pattern)


def _validate_range(rule: RangeRuleSpec) -> None:
    if rule.minimum is None and rule.maximum is None:
        raise ValidationInputError("range requires at least one boundary")
    for boundary in (rule.minimum, rule.maximum):
        if boundary is None:
            continue
        if isinstance(boundary, bool) or not isinstance(boundary, (int, float)):
            raise ValidationInputError("range boundaries must be finite numbers")
        if not math.isfinite(boundary):
            raise ValidationInputError("range boundaries must be finite numbers")
    if rule.minimum is not None and rule.maximum is not None and rule.minimum > rule.maximum:
        raise ValidationInputError("range minimum must not exceed maximum")
