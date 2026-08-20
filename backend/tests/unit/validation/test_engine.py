import math
from dataclasses import FrozenInstanceError
from typing import Any, cast
from uuid import uuid4

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from datacheck.validation import (
    RangeRuleSpec,
    RegexRuleSpec,
    RequiredRuleSpec,
    TypeRuleSpec,
    UniqueRuleSpec,
    ValidationEngineResult,
    ValidationInputError,
    ValidationRuleSpec,
    validate,
)


def test_engine_preserves_rule_order_is_deterministic_and_does_not_mutate_data() -> None:
    data = pl.DataFrame(
        {
            "name": ["Ada", "", "Ada"],
            "age": ["36", "invalid", None],
            "email": ["ada@example.com", "bad", "grace@example.com"],
        },
        schema={"name": pl.String, "age": pl.String, "email": pl.String},
    )
    original = data.clone()
    rules: list[ValidationRuleSpec] = [
        RegexRuleSpec(uuid4(), "email", r"^[^@]+@[^@]+$"),
        UniqueRuleSpec(uuid4(), "name"),
        RequiredRuleSpec(uuid4(), "name"),
        TypeRuleSpec(uuid4(), "age", "integer"),
        RangeRuleSpec(uuid4(), "age", minimum=0, maximum=130),
    ]

    first = validate(data, rules)
    second = validate(data, rules)

    assert first == second
    assert first.total_rows == 3
    assert [result.rule for result in first.rule_results] == rules
    assert [result.violation_count for result in first.rule_results] == [1, 1, 1, 1, 1]
    assert_frame_equal(data, original)


def test_header_only_data_frame_returns_zero_counts_for_all_rules() -> None:
    data = pl.DataFrame(schema={"value": pl.String})
    rules: list[ValidationRuleSpec] = [
        RequiredRuleSpec(uuid4(), "value"),
        UniqueRuleSpec(uuid4(), "value"),
        TypeRuleSpec(uuid4(), "value", "integer"),
        RangeRuleSpec(uuid4(), "value", minimum=0),
        RegexRuleSpec(uuid4(), "value", "value"),
    ]

    result = validate(data, rules)

    assert result.total_rows == 0
    for rule_result in result.rule_results:
        assert (
            rule_result.evaluated_count,
            rule_result.passed_count,
            rule_result.violation_count,
            rule_result.skipped_count,
            rule_result.violation_samples,
        ) == (0, 0, 0, 0, ())


def test_results_and_rule_specs_are_immutable() -> None:
    rule = RequiredRuleSpec(uuid4(), "value")
    result = validate(pl.DataFrame({"value": [""]}), [rule])

    with pytest.raises(FrozenInstanceError):
        rule.target_column = "other"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.total_rows = 2  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.rule_results[0].violation_count = 0  # type: ignore[misc]


def test_validation_requires_unique_rule_ids() -> None:
    rule_id = uuid4()
    data = pl.DataFrame({"value": ["x"]})

    with pytest.raises(ValidationInputError, match="rule IDs must be unique"):
        validate(
            data,
            [RequiredRuleSpec(rule_id, "value"), UniqueRuleSpec(rule_id, "value")],
        )


@pytest.mark.parametrize(
    ("data", "rule", "message"),
    [
        (
            pl.DataFrame({"value": ["x"]}),
            RequiredRuleSpec(uuid4(), "missing"),
            "target column does not exist",
        ),
        (
            pl.DataFrame({"value": [1]}),
            RequiredRuleSpec(uuid4(), "value"),
            "target column must use the Polars String dtype",
        ),
        (
            pl.DataFrame({"value": ["x"]}),
            TypeRuleSpec(uuid4(), "value", cast(Any, "uuid")),
            "expected type is unsupported",
        ),
        (
            pl.DataFrame({"value": ["x"]}),
            TypeRuleSpec(uuid4(), "value", cast(Any, ["integer"])),
            "expected type is unsupported",
        ),
        (
            pl.DataFrame({"value": ["1"]}),
            RangeRuleSpec(uuid4(), "value"),
            "range requires at least one boundary",
        ),
        (
            pl.DataFrame({"value": ["1"]}),
            RangeRuleSpec(uuid4(), "value", minimum=2, maximum=1),
            "range minimum must not exceed maximum",
        ),
        (
            pl.DataFrame({"value": ["x"]}),
            RegexRuleSpec(uuid4(), "value", "("),
            "regex pattern is invalid",
        ),
    ],
)
def test_engine_rejects_invalid_structural_inputs(
    data: pl.DataFrame,
    rule: RequiredRuleSpec | TypeRuleSpec | RangeRuleSpec | RegexRuleSpec,
    message: str,
) -> None:
    with pytest.raises(ValidationInputError, match=message):
        validate(data, [rule])


@pytest.mark.parametrize("boundary", [math.nan, math.inf, -math.inf, True, "1"])
def test_engine_rejects_non_finite_or_non_numeric_range_boundaries(boundary: object) -> None:
    rule = RangeRuleSpec(uuid4(), "value", minimum=cast(Any, boundary))

    with pytest.raises(ValidationInputError, match="range boundaries must be finite numbers"):
        validate(pl.DataFrame({"value": ["1"]}), [rule])


def test_engine_rejects_non_dataframe_input() -> None:
    with pytest.raises(ValidationInputError, match="data must be a Polars DataFrame"):
        validate(cast(Any, {"value": ["x"]}), [])


def test_engine_rejects_non_uuid_rule_id() -> None:
    rule = RequiredRuleSpec(cast(Any, "rule-1"), "value")

    with pytest.raises(ValidationInputError, match="rule ID must be a UUID"):
        validate(pl.DataFrame({"value": ["x"]}), [rule])


def test_engine_result_is_an_explicit_domain_value() -> None:
    result = validate(pl.DataFrame(schema={"value": pl.String}), [])

    assert result == ValidationEngineResult(total_rows=0, rule_results=())
