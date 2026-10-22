from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gridbot.domain import (
    DomainError,
    FloatNotAllowedError,
    ceil_to_increment,
    floor_to_increment,
    is_multiple_of,
)

D = Decimal

TICKS = [D("0.01"), D("0.10"), D("0.05"), D("1"), D("10")]
STEPS = [D("0.00001"), D("0.0001"), D("0.001"), D("0.05"), D("1")]


# ------------------------------------------------------------------ exemplos do enunciado


@pytest.mark.parametrize("raw", ["65000.00", "65000.10", "65000.20", "65000", "0.10", "0"])
def test_tick_010_aligned(raw: str) -> None:
    assert is_multiple_of(D(raw), D("0.10"))


@pytest.mark.parametrize("raw", ["65000.15", "65000.01", "0.05", "65000.11"])
def test_tick_010_not_aligned(raw: str) -> None:
    assert not is_multiple_of(D(raw), D("0.10"))


@pytest.mark.parametrize("raw", ["0.00001", "0.00002", "0.12345", "1"])
def test_step_000001_aligned(raw: str) -> None:
    assert is_multiple_of(D(raw), D("0.00001"))


def test_step_000001_not_aligned() -> None:
    assert not is_multiple_of(D("0.000015"), D("0.00001"))


def test_multiple_is_mathematical_not_decimal_places() -> None:
    # 0.07 tem duas casas, como 0.05, mas não é múltiplo de 0.05.
    assert not is_multiple_of(D("0.07"), D("0.05"))
    assert floor_to_increment(D("0.07"), D("0.05")) == D("0.05")
    assert ceil_to_increment(D("0.07"), D("0.05")) == D("0.10")
    # E o contrário: 0.1 tem uma casa e é múltiplo de 0.05.
    assert is_multiple_of(D("0.1"), D("0.05"))


def test_decimal_avoids_the_classic_binary_float_problem() -> None:
    assert 0.1 * 3 != 0.3  # float binário erra (ilustração; float é proibido no domínio)
    assert D("0.1") * 3 == D("0.3")
    assert is_multiple_of(D("0.3"), D("0.1"))
    assert floor_to_increment(D("0.3"), D("0.1")) == D("0.3")
    assert ceil_to_increment(D("0.3"), D("0.1")) == D("0.3")


@pytest.mark.parametrize(
    ("value", "increment", "floor", "ceil"),
    [
        ("100.19", "0.10", "100.10", "100.20"),
        ("100.20", "0.10", "100.20", "100.20"),
        ("0.001239", "0.00001", "0.00123", "0.00124"),
        ("0.00124", "0.00001", "0.00124", "0.00124"),
        ("65000.15", "0.10", "65000.10", "65000.20"),
        ("65000.149", "0.05", "65000.10", "65000.15"),
        ("1234.5", "1", "1234", "1235"),
        ("1234.5", "10", "1230", "1240"),
        ("0.5", "10", "0", "10"),
        ("0", "0.01", "0", "0"),
    ],
)
def test_floor_and_ceil_examples(value: str, increment: str, floor: str, ceil: str) -> None:
    assert floor_to_increment(D(value), D(increment)) == D(floor)
    assert ceil_to_increment(D(value), D(increment)) == D(ceil)


@pytest.mark.parametrize("increment", TICKS + STEPS)
def test_one_increment_below_and_above_an_aligned_value(increment: Decimal) -> None:
    aligned = increment * 1000
    tiny = D("0.000000001")
    assert is_multiple_of(aligned, increment)
    assert not is_multiple_of(aligned - tiny, increment)
    assert not is_multiple_of(aligned + tiny, increment)
    assert is_multiple_of(aligned - increment, increment)
    assert is_multiple_of(aligned + increment, increment)
    assert floor_to_increment(aligned - tiny, increment) == aligned - increment
    assert ceil_to_increment(aligned + tiny, increment) == aligned + increment


def test_very_large_and_very_small_values_within_precision() -> None:
    assert is_multiple_of(D("123456789012.34"), D("0.01"))
    assert floor_to_increment(D("123456789012.349"), D("0.01")) == D("123456789012.34")
    assert ceil_to_increment(D("0.000000011"), D("0.00000001")) == D("0.00000002")
    assert floor_to_increment(D("0.000000011"), D("0.00000001")) == D("0.00000001")


def test_beyond_financial_precision_fails_instead_of_rounding() -> None:
    with pytest.raises(DomainError, match="precisão"):
        is_multiple_of(D("1E+40"), D("0.00000001"))


@pytest.mark.parametrize("increment", ["0", "-0.01"])
def test_non_positive_increment_is_rejected(increment: str) -> None:
    with pytest.raises(DomainError):
        floor_to_increment(D("1"), D(increment))


def test_negative_value_is_rejected() -> None:
    with pytest.raises(DomainError):
        ceil_to_increment(D("-1"), D("0.1"))


def test_float_and_non_finite_are_rejected() -> None:
    with pytest.raises(FloatNotAllowedError):
        is_multiple_of(0.3, D("0.1"))  # type: ignore[arg-type]
    with pytest.raises(DomainError):
        is_multiple_of(D("NaN"), D("0.1"))
    with pytest.raises(DomainError):
        floor_to_increment(D("1"), D("Infinity"))


# ------------------------------------------------------------------ propriedades

values = st.decimals(
    min_value=0, max_value=D("1e12"), places=10, allow_nan=False, allow_infinity=False
)
increments = st.one_of(
    st.sampled_from(TICKS + STEPS + [D("0.00000001"), D("0.25"), D("100")]),
    st.decimals(
        min_value=D("0.00000001"), max_value=D("1000"), places=8, allow_infinity=False
    ).filter(lambda d: d > 0),
)


@given(values, increments)
def test_floor_and_ceil_bracket_the_value_on_the_grid(value: Decimal, increment: Decimal) -> None:
    floor = floor_to_increment(value, increment)
    ceil = ceil_to_increment(value, increment)
    assert floor <= value <= ceil
    assert is_multiple_of(floor, increment)
    assert is_multiple_of(ceil, increment)
    assert ceil - floor <= increment
    assert (ceil - floor == 0) == is_multiple_of(value, increment)


@given(st.integers(min_value=0, max_value=10**12), increments)
def test_aligned_values_are_fixed_points(n: int, increment: Decimal) -> None:
    aligned = increment * n
    assert is_multiple_of(aligned, increment)
    assert floor_to_increment(aligned, increment) == aligned
    assert ceil_to_increment(aligned, increment) == aligned
