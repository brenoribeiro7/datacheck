from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal, localcontext

from datacheck.validation import RuleValidationResult

_SCORE_QUANTUM = Decimal("0.01")


def calculate_quality_score(results: Sequence[RuleValidationResult]) -> Decimal | None:
    passed = sum(result.passed_count for result in results)
    evaluated = sum(result.evaluated_count for result in results)
    if evaluated == 0:
        return None
    with localcontext() as context:
        context.prec = 40
        score = Decimal(100) * Decimal(passed) / Decimal(evaluated)
        return score.quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP)
