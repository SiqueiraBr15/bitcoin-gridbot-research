from __future__ import annotations

from decimal import Decimal, DivisionByZero, Inexact
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gridbot.domain import (
    DomainError,
    FloatNotAllowedError,
    financial,
    require_finite,
    to_decimal,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0", "0"),
        ("65000.12345678", "65000.12345678"),
        ("0.00000001", "1E-8"),
        ("-1.5", "-1.5"),
        ("+2", "2"),
        ("1e3", "1E+3"),
        (".5", "0.5"),
        ("10.", "10"),
    ],
)
def test_string_input_becomes_exact_decimal(raw: str, expected: str) -> None:
    value = to_decimal(raw)
    assert type(value) is Decimal
    assert value == Decimal(expected)


def test_string_arithmetic_is_exact_where_float_is_not() -> None:
    assert 0.1 + 0.2 != 0.3  # float erra...
    assert to_decimal("0.1") + to_decimal("0.2") == Decimal("0.3")  # ...Decimal não


def test_int_and_decimal_inputs_are_accepted() -> None:
    assert to_decimal(42) == Decimal(42)
    assert to_decimal(Decimal("1.10")) == Decimal("1.10")


@pytest.mark.parametrize("raw", [0.1, 1.0, 0.0, -2.5])
def test_float_input_is_rejected(raw: float) -> None:
    with pytest.raises(FloatNotAllowedError):
        to_decimal(cast(Any, raw))


@given(st.floats(allow_nan=True, allow_infinity=True))
def test_every_float_is_rejected(value: float) -> None:
    with pytest.raises(FloatNotAllowedError):
        to_decimal(cast(Any, value))


@pytest.mark.parametrize(
    "raw",
    ["NaN", "nan", "sNaN", "Infinity", "-Infinity", "inf", "", " 1", "1 ", "1_000", "1,5", "0x10"],
)
def test_invalid_or_non_finite_strings_are_rejected(raw: str) -> None:
    with pytest.raises(DomainError):
        to_decimal(raw)


@pytest.mark.parametrize(
    "raw", [Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity")]
)
def test_non_finite_decimal_is_rejected(raw: Decimal) -> None:
    with pytest.raises(DomainError):
        to_decimal(raw)


def test_bool_and_unsupported_types_are_rejected() -> None:
    with pytest.raises(DomainError):
        to_decimal(cast(Any, True))
    with pytest.raises(TypeError):
        to_decimal(cast(Any, [1]))


def test_require_finite_does_not_convert() -> None:
    assert require_finite(Decimal("3")) == Decimal("3")
    with pytest.raises(FloatNotAllowedError):
        require_finite(3.0)
    with pytest.raises(TypeError):
        require_finite("3")


@given(st.decimals(allow_nan=False, allow_infinity=False))
def test_finite_decimal_survives_string_roundtrip(value: Decimal) -> None:
    parsed = to_decimal(str(value))
    assert type(parsed) is Decimal
    assert parsed.is_finite()
    assert parsed == value


def test_financial_context_traps_implicit_rounding_and_division_by_zero() -> None:
    with financial():
        with pytest.raises(Inexact):
            _ = Decimal(1) / Decimal(3)
        with pytest.raises(DivisionByZero):
            _ = Decimal(1) / Decimal(0)
