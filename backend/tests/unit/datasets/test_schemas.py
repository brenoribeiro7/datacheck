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
