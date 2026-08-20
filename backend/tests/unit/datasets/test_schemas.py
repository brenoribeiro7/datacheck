import math

import pytest
from pydantic import TypeAdapter, ValidationError

from datacheck.datasets.schemas import RuleCreateRequest, canonical_rule_configuration

_ADAPTER: TypeAdapter[RuleCreateRequest] = TypeAdapter(RuleCreateRequest)


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "required", "target_column": "id", "configuration": {}},
        {"type": "unique", "target_column": "id", "configuration": {}},
        {
            "type": "type",
            "target_column": "age",
            "configuration": {"expected_type": "integer"},
        },
        {
            "type": "range",
            "target_column": "age",
            "configuration": {"minimum": 0, "maximum": 130},
        },
        {
            "type": "regex",
            "target_column": "email",
            "configuration": {"pattern": r"^[^@]+@[^@]+$"},
        },
    ],
)
def test_rule_requests_are_discriminated_and_canonical(payload: dict[str, object]) -> None:
    parsed = _ADAPTER.validate_python(payload)
    configuration = canonical_rule_configuration(parsed)
    assert configuration == payload["configuration"] or (
        payload["type"] == "range" and configuration == {"minimum": 0.0, "maximum": 130.0}
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "required", "target_column": "id", "configuration": {"x": 1}},
        {"type": "type", "target_column": "age", "configuration": {"expected_type": "uuid"}},
        {"type": "range", "target_column": "age", "configuration": {}},
        {
            "type": "range",
            "target_column": "age",
            "configuration": {"minimum": 2, "maximum": 1},
        },
        {"type": "regex", "target_column": "value", "configuration": {"pattern": "("}},
        {"type": "custom", "target_column": "value", "configuration": {}},
    ],
)
def test_rule_requests_reject_invalid_or_extra_configuration(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python(payload)


@pytest.mark.parametrize("boundary", [math.inf, -math.inf, math.nan])
def test_range_rejects_non_finite_numbers(boundary: float) -> None:
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python(
            {
                "type": "range",
                "target_column": "age",
                "configuration": {"minimum": boundary},
            }
        )


@pytest.mark.parametrize(
    ("configuration", "expected"),
    [
        ({"minimum": 0}, {"minimum": 0.0, "maximum": None}),
        ({"minimum": 1}, {"minimum": 1.0, "maximum": None}),
        ({"minimum": -1}, {"minimum": -1.0, "maximum": None}),
        ({"minimum": 1.5}, {"minimum": 1.5, "maximum": None}),
        ({"maximum": 10}, {"minimum": None, "maximum": 10.0}),
        ({"minimum": 1, "maximum": 2.5}, {"minimum": 1.0, "maximum": 2.5}),
    ],
)
def test_range_accepts_only_real_json_numbers(
    configuration: dict[str, object], expected: dict[str, object]
) -> None:
    parsed = _ADAPTER.validate_python(
        {"type": "range", "target_column": "age", "configuration": configuration}
    )
    assert canonical_rule_configuration(parsed) == expected


@pytest.mark.parametrize(
    "configuration",
    [
        {"minimum": True},
        {"minimum": False},
        {"maximum": True},
        {"maximum": False},
        {"minimum": "1"},
        {"minimum": "1.5"},
        {"maximum": "2"},
        {"maximum": ""},
    ],
)
def test_range_rejects_booleans_and_strings(configuration: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python(
            {"type": "range", "target_column": "age", "configuration": configuration}
        )
