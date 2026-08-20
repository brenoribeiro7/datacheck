from decimal import Decimal
from uuid import uuid4

import pytest

from datacheck.analysis.score import calculate_quality_score
from datacheck.validation import RequiredRuleSpec, RuleValidationResult


def _result(*, evaluated: int, passed: int, skipped: int = 0) -> RuleValidationResult:
    return RuleValidationResult(
        rule=RequiredRuleSpec(uuid4(), "value"),
        evaluated_count=evaluated,
        passed_count=passed,
        violation_count=evaluated - passed,
        skipped_count=skipped,
        violation_samples=(),
    )


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        ([_result(evaluated=10, passed=10)], Decimal("100.00")),
        ([_result(evaluated=10, passed=0)], Decimal("0.00")),
        ([_result(evaluated=6, passed=5)], Decimal("83.33")),
        (
            [_result(evaluated=2, passed=1), _result(evaluated=1, passed=1)],
            Decimal("66.67"),
        ),
        ([_result(evaluated=0, passed=0, skipped=12)], None),
        ([], None),
    ],
)
def test_quality_score_contract(
    results: list[RuleValidationResult], expected: Decimal | None
) -> None:
    assert calculate_quality_score(results) == expected
    assert calculate_quality_score(results) == expected


def test_quality_score_uses_round_half_up_and_excludes_skipped_rows() -> None:
    assert calculate_quality_score([_result(evaluated=160, passed=133, skipped=10)]) == Decimal(
        "83.13"
    )
    assert calculate_quality_score([_result(evaluated=32, passed=1)]) == Decimal("3.13")
