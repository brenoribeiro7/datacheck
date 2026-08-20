from collections.abc import Sequence
from uuid import uuid4

import polars as pl
import pytest

from datacheck.validation import (
    VALUE_PREVIEW_LIMIT,
    VIOLATION_SAMPLE_LIMIT,
    ExpectedType,
    RangeRuleSpec,
    RegexRuleSpec,
    RequiredRuleSpec,
    RuleValidationResult,
    TypeRuleSpec,
    UniqueRuleSpec,
    validate,
)


def _single_result(
    values: Sequence[str | None],
    rule: RequiredRuleSpec | UniqueRuleSpec | TypeRuleSpec | RangeRuleSpec | RegexRuleSpec,
) -> RuleValidationResult:
    return validate(
        pl.DataFrame({"value": values}, schema={"value": pl.String}), [rule]
    ).rule_results[0]


def _assert_count_invariants(total_rows: int, result: RuleValidationResult) -> None:
    assert result.evaluated_count == result.passed_count + result.violation_count
    assert total_rows == result.evaluated_count + result.skipped_count


def test_required_uses_the_shared_missing_semantics() -> None:
    values = ["A", None, "", "   ", "\t", "\u2003", "NA", "N/A"]

    result = _single_result(values, RequiredRuleSpec(uuid4(), "value"))

    assert (result.evaluated_count, result.passed_count, result.violation_count) == (8, 3, 5)
    assert result.skipped_count == 0
    assert [(sample.row_number, sample.value_preview) for sample in result.violation_samples] == [
        (2, None),
        (3, ""),
        (4, "   "),
        (5, "\t"),
        (6, "\u2003"),
    ]
    _assert_count_invariants(len(values), result)


def test_unique_is_exact_first_occurrence_wins_and_skips_missing() -> None:
    values = ["A", "A", "A", "a", " A", None, "", " ", "B", "B"]

    result = _single_result(values, UniqueRuleSpec(uuid4(), "value"))

    assert (result.evaluated_count, result.passed_count, result.violation_count) == (7, 4, 3)
    assert result.skipped_count == 3
    assert [sample.row_number for sample in result.violation_samples] == [2, 3, 10]
    _assert_count_invariants(len(values), result)


def test_unique_counts_all_violations_after_the_sample_limit() -> None:
    values = [f"value-{index}" for index in range(25)] * 2

    result = _single_result(values, UniqueRuleSpec(uuid4(), "value"))

    assert result.violation_count == 25
    assert len(result.violation_samples) == VIOLATION_SAMPLE_LIMIT
    assert [sample.row_number for sample in result.violation_samples] == list(range(26, 46))
    _assert_count_invariants(len(values), result)


@pytest.mark.parametrize(
    ("expected_type", "valid", "invalid"),
    [
        ("string", ["text", " A ", "NA"], []),
        ("integer", ["0", "1", "-12", "+007"], ["1.0", "1e3", " 1", "1 ", "١", "NaN"]),
        (
            "number",
            ["1", "-1", "1.5", ".5", "1e3", "-2.5E-4"],
            ["1.", "NaN", "Infinity", "-Infinity", "1,5", " 1", "1 ", "١"],
        ),
        ("boolean", ["true", "TRUE", "False", "FALSE"], ["yes", "no", "1", "0", " true", "true "]),
        (
            "date",
            ["2026-08-20", "2024-02-29"],
            ["20/08/2026", "2026-2-1", "2026-02-30", " 2026-08-20"],
        ),
        (
            "datetime",
            [
                "2026-08-20T12:30:00Z",
                "2026-08-20T09:30:00-03:00",
                "2026-08-20T12:30:00.1+02:00",
                "2026-08-20T12:30:00.123456Z",
            ],
            [
                "2026-08-20",
                "2026-08-20T12:30",
                "2026-08-20T12:30:00",
                "2026-08-20 12:30:00Z",
                " 2026-08-20T12:30:00Z",
                "2026-02-30T12:30:00Z",
                "2026-08-20T25:30:00Z",
                "2026-08-20T12:30:00.1234567Z",
            ],
        ),
    ],
)
def test_type_contracts_are_strict_and_missing_is_skipped(
    expected_type: ExpectedType, valid: list[str], invalid: list[str]
) -> None:
    values: list[str | None] = [*valid, *invalid, None, "", " "]

    result = _single_result(
        values,
        TypeRuleSpec(uuid4(), "value", expected_type),
    )

    assert result.evaluated_count == len(valid) + len(invalid)
    assert result.passed_count == len(valid)
    assert result.violation_count == len(invalid)
    assert result.skipped_count == 3
    _assert_count_invariants(len(values), result)


@pytest.mark.parametrize(
    ("rule", "values", "expected_violations"),
    [
        (RangeRuleSpec(uuid4(), "value", minimum=0), ["0", "1", "-1", ".5", "1e2"], 1),
        (RangeRuleSpec(uuid4(), "value", maximum=2.5), ["2.5", "2.6", "-10"], 1),
        (
            RangeRuleSpec(uuid4(), "value", minimum=-1.5, maximum=2.5),
            ["-1.5", "2.5", "-1.6", "2.6", "abc", "1."],
            4,
        ),
    ],
)
def test_range_uses_inclusive_boundaries_and_the_number_grammar(
    rule: RangeRuleSpec, values: list[str], expected_violations: int
) -> None:
    with_missing: list[str | None] = [*values, None, "", "\t"]

    result = _single_result(with_missing, rule)

    assert result.violation_count == expected_violations
    assert result.skipped_count == 3
    _assert_count_invariants(len(with_missing), result)


@pytest.mark.parametrize(
    ("pattern", "values", "violating_rows"),
    [
        ("foo", ["xxfooyy", "bar", "Foo"], [2, 3]),
        ("^foo$", ["foo", "xfoo", "foox"], [2, 3]),
        ("(?i)foo", ["Foo", "FOO", "bar"], [3]),
    ],
)
def test_regex_uses_polars_contains_semantics(
    pattern: str, values: list[str], violating_rows: list[int]
) -> None:
    with_missing: list[str | None] = [*values, None, "", " "]

    result = _single_result(with_missing, RegexRuleSpec(uuid4(), "value", pattern))

    assert [sample.row_number for sample in result.violation_samples] == violating_rows
    assert result.skipped_count == 3
    _assert_count_invariants(len(with_missing), result)


def test_violation_previews_preserve_original_values_and_are_bounded() -> None:
    exact = "x" * VALUE_PREVIEW_LIMIT
    longer = "y" * (VALUE_PREVIEW_LIMIT + 1)

    result = _single_result(
        [None, "   ", exact, longer],
        RegexRuleSpec(uuid4(), "value", "never-matches"),
    )

    assert result.violation_count == 2
    assert result.skipped_count == 2
    assert result.violation_samples[0].value_preview == exact
    assert result.violation_samples[0].truncated is False
    assert result.violation_samples[1].value_preview == "y" * VALUE_PREVIEW_LIMIT
    assert result.violation_samples[1].truncated is True
