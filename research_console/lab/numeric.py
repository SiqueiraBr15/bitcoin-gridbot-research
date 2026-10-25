"""Exact, bounded rational transport, independent of Python's int/string setting.

The pack's unchanged decimal grammar has <=80 coefficient digits, adjusted
exponent [-100,20], hence numerator and denominator each have <=200 digits.
Conservation gives B*P/N = 1-C/N: each reduced exposure denominator has <=400
digits. There are <=MAX_MARKS terms in the entire pack, not per account. A sum
uses at most their denominator product; cadence/time factors need <=16 extra
digits. This conservative bound admits every validated v1 exposure, including
coprime denominators, without permitting arbitrary unbounded transport strings.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from fractions import Fraction
from functools import wraps

from research_console.lab.packs import MAX_MARKS

MAX_INTEGER_DIGITS = 400 * MAX_MARKS + 16
MAX_INTEGER_BITS = (MAX_INTEGER_DIGITS * 3322 + 999) // 1000
MAX_ANALYSIS_BYTES = 64 * 1024 * 1024
NUMERIC_CONTRACT = "EXACT_RATIONAL_DECIMAL_V2"


class AnalysisError(RuntimeError):
    """A calculation/transport failure is not an invalid Evidence Pack."""


def calculated[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return function(*args, **kwargs)
        except (ArithmeticError, ValueError, TypeError) as error:
            raise AnalysisError("Internal analytical calculation failed") from error

    return wrapped


def integer_text(value: int) -> str:
    """Decimal(int) is exact/context independent; no global safety switch changes."""
    if value.bit_length() > MAX_INTEGER_BITS:
        raise AnalysisError("Derived integer exceeds the numeric contract")
    text = str(Decimal(value))
    if len(text.lstrip("-")) > MAX_INTEGER_DIGITS:
        raise AnalysisError("Derived integer exceeds the numeric contract")
    return text


def exact(value: Fraction) -> str:
    """Keep the existing JSON string contract: integer or numerator/denominator."""
    numerator = integer_text(value.numerator)
    return (
        numerator if value.denominator == 1 else numerator + "/" + integer_text(value.denominator)
    )


def balanced_sum(values: list[Fraction]) -> Fraction:
    """A balanced tree avoids repeatedly adding short terms to a huge denominator."""
    while len(values) > 1:
        values = [
            values[i] + values[i + 1] if i + 1 < len(values) else values[i]
            for i in range(0, len(values), 2)
        ]
    return values[0] if values else Fraction(0)
