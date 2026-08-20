import math
import re
from collections.abc import Callable, Sequence
from datetime import date, datetime
from typing import cast

import polars as pl
from polars.exceptions import PolarsError

from datacheck.validation.models import (
    VALUE_PREVIEW_LIMIT,
    VIOLATION_SAMPLE_LIMIT,
    ExpectedType,
    RangeRuleSpec,
    RegexRuleSpec,
    RequiredRuleSpec,
    RuleValidationResult,
    TypeRuleSpec,
    UniqueRuleSpec,
    ValidationInputError,
    ValidationRuleSpec,
    ViolationSample,
)

_INTEGER_PATTERN = re.compile(r"[+-]?[0-9]+")
_NUMBER_PATTERN = re.compile(r"[+-]?(?:[0-9]+(?:[.][0-9]+)?|[.][0-9]+)(?:[eE][+-]?[0-9]+)?")
_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_DATETIME_PATTERN = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:[.][0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})"
)


def is_missing(value: str | None) -> bool:
    """Detect absence without changing the original value used by other rules."""
    return value is None or value == "" or value.strip() == ""


def validate_regex_pattern(pattern: object) -> None:
    if not isinstance(pattern, str) or not pattern:
        raise ValidationInputError("regex pattern must be a non-empty string")
    try:
        pl.Series([""], dtype=pl.String).str.contains(pattern).to_list()
    except PolarsError:
        raise ValidationInputError("regex pattern is invalid for the Polars dialect") from None


def evaluate_rule(values: Sequence[str | None], rule: ValidationRuleSpec) -> RuleValidationResult:
    if isinstance(rule, RequiredRuleSpec):
        return _evaluate_required(values, rule)
    if isinstance(rule, UniqueRuleSpec):
        return _evaluate_unique(values, rule)
    if isinstance(rule, TypeRuleSpec):
        return _evaluate_non_missing(
            values,
            rule,
            lambda value: _matches_type(value, rule.expected_type),
        )
    if isinstance(rule, RangeRuleSpec):
        return _evaluate_non_missing(values, rule, lambda value: _within_range(value, rule))
    if isinstance(rule, RegexRuleSpec):
        return _evaluate_regex(values, rule)
    raise ValidationInputError("unsupported validation rule")


def _evaluate_required(
    values: Sequence[str | None], rule: RequiredRuleSpec
) -> RuleValidationResult:
    samples: list[ViolationSample] = []
    violation_count = 0
    for row_number, value in enumerate(values, start=1):
        if is_missing(value):
            violation_count += 1
            _append_sample(samples, row_number, value)
    evaluated_count = len(values)
    return _result(
        rule=rule,
        evaluated_count=evaluated_count,
        violation_count=violation_count,
        skipped_count=0,
        samples=samples,
    )


def _evaluate_unique(values: Sequence[str | None], rule: UniqueRuleSpec) -> RuleValidationResult:
    seen: set[str] = set()
    samples: list[ViolationSample] = []
    violation_count = 0
    skipped_count = 0
    for row_number, value in enumerate(values, start=1):
        if is_missing(value):
            skipped_count += 1
            continue
        assert value is not None
        # Membership is the only set behavior used: row order, not set order,
        # determines which occurrence wins and which samples are returned.
        if value in seen:
            violation_count += 1
            _append_sample(samples, row_number, value)
        else:
            seen.add(value)
    return _result(
        rule=rule,
        evaluated_count=len(values) - skipped_count,
        violation_count=violation_count,
        skipped_count=skipped_count,
        samples=samples,
    )


def _evaluate_non_missing(
    values: Sequence[str | None],
    rule: TypeRuleSpec | RangeRuleSpec,
    passes: Callable[[str], bool],
) -> RuleValidationResult:
    samples: list[ViolationSample] = []
    violation_count = 0
    skipped_count = 0
    for row_number, value in enumerate(values, start=1):
        if is_missing(value):
            skipped_count += 1
            continue
        assert value is not None
        if not passes(value):
            violation_count += 1
            _append_sample(samples, row_number, value)
    return _result(
        rule=rule,
        evaluated_count=len(values) - skipped_count,
        violation_count=violation_count,
        skipped_count=skipped_count,
        samples=samples,
    )


def _evaluate_regex(values: Sequence[str | None], rule: RegexRuleSpec) -> RuleValidationResult:
    try:
        matches = cast(
            list[bool | None],
            pl.Series("value", values, dtype=pl.String).str.contains(rule.pattern).to_list(),
        )
    except PolarsError:
        raise ValidationInputError("regex pattern is invalid for the Polars dialect") from None

    samples: list[ViolationSample] = []
    violation_count = 0
    skipped_count = 0
    for row_number, (value, matches_pattern) in enumerate(
        zip(values, matches, strict=True), start=1
    ):
        if is_missing(value):
            skipped_count += 1
            continue
        if matches_pattern is not True:
            violation_count += 1
            _append_sample(samples, row_number, value)
    return _result(
        rule=rule,
        evaluated_count=len(values) - skipped_count,
        violation_count=violation_count,
        skipped_count=skipped_count,
        samples=samples,
    )


def _matches_type(value: str, expected_type: ExpectedType) -> bool:
    if expected_type == "string":
        return True
    if expected_type == "integer":
        return _INTEGER_PATTERN.fullmatch(value) is not None
    if expected_type == "number":
        return _parse_number(value) is not None
    if expected_type == "boolean":
        return value.casefold() in {"true", "false"}
    if expected_type == "date":
        return _is_date(value)
    if expected_type == "datetime":
        return _is_datetime(value)
    raise ValidationInputError("unsupported expected type")


def _parse_number(value: str) -> float | None:
    # One explicit ASCII grammar is shared by type(number) and range.
    if _NUMBER_PATTERN.fullmatch(value) is None:
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _is_date(value: str) -> bool:
    if _DATE_PATTERN.fullmatch(value) is None:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_datetime(value: str) -> bool:
    # fromisoformat is intentionally gated by the narrower public grammar.
    if _DATETIME_PATTERN.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.utcoffset() is not None


def _within_range(value: str, rule: RangeRuleSpec) -> bool:
    parsed = _parse_number(value)
    if parsed is None:
        return False
    if rule.minimum is not None and parsed < rule.minimum:
        return False
    return rule.maximum is None or parsed <= rule.maximum


def _append_sample(samples: list[ViolationSample], row_number: int, value: str | None) -> None:
    # Counting continues after this bounded collection is full.
    if len(samples) >= VIOLATION_SAMPLE_LIMIT:
        return
    preview = None if value is None else value[:VALUE_PREVIEW_LIMIT]
    samples.append(
        ViolationSample(
            row_number=row_number,
            value_preview=preview,
            truncated=value is not None and len(value) > VALUE_PREVIEW_LIMIT,
        )
    )


def _result(
    *,
    rule: ValidationRuleSpec,
    evaluated_count: int,
    violation_count: int,
    skipped_count: int,
    samples: list[ViolationSample],
) -> RuleValidationResult:
    return RuleValidationResult(
        rule=rule,
        evaluated_count=evaluated_count,
        passed_count=evaluated_count - violation_count,
        violation_count=violation_count,
        skipped_count=skipped_count,
        violation_samples=tuple(samples),
    )
