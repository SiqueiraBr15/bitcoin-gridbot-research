"""A15.1: oráculos exatos independentes do contexto do código sob teste."""

from __future__ import annotations

from decimal import Decimal, Inexact, localcontext
from fractions import Fraction
from itertools import pairwise

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gridbot.domain import BTCUSDT, USDT, DomainError, GridLevel, Money, Price, Qty
from gridbot.domain.rules import MarketRules, NotionalRules, PriceRules, QuantityRules
from gridbot.strategy.arithmetic_grid import (
    ArithmeticGridPlan,
    ArithmeticGridSpec,
    build_arithmetic_grid,
)


def ticks(units: int, exponent: int) -> Decimal:
    return Decimal((0, tuple(int(c) for c in str(units)), exponent))


def market(tick: Decimal) -> MarketRules:
    return MarketRules(
        BTCUSDT, PriceRules(Price(tick)), QuantityRules(Qty.parse("0.001"), Qty.parse("0.001"))
    )


@pytest.mark.parametrize("precision", [2, 28, 34, 50])
def test_nonuniform_direct_plan_is_rejected_in_every_ambient_context(precision: int) -> None:
    p = Price.parse
    with localcontext() as ctx:
        ctx.prec = precision
        with pytest.raises(DomainError):
            ArithmeticGridPlan(
                ArithmeticGridSpec(BTCUSDT, p("100"), p("102"), 2),
                p("0.001"),
                tuple(GridLevel(i, p(v)) for i, v in enumerate(("100", "101.001", "102"))),
            )


@pytest.mark.parametrize("precision", [2, 28, 34, 50])
def test_step_preserves_all_33_fractional_digits(precision: int) -> None:
    lower, upper = Price.parse("1"), Price.parse("1.123456789012345678901234567890123")
    with localcontext() as ctx:
        ctx.prec = precision
        plan = ArithmeticGridPlan(
            ArithmeticGridSpec(BTCUSDT, lower, upper, 1),
            Price.parse("1e-33"),
            (GridLevel(0, lower), GridLevel(1, upper)),
        )
        assert Fraction(plan.step) == Fraction(upper.value) - Fraction(lower.value)
        assert plan.step_ticks == 123456789012345678901234567890123


@settings(max_examples=150, deadline=None, derandomize=True)
@given(
    st.integers(1, 10**16),
    st.integers(1, 999),
    st.integers(1, 400),
    st.integers(-12, 12),
    st.integers(2, 40),
)
def test_integer_tick_oracle_across_magnitudes_and_hundreds_of_intervals(
    lower_units: int,
    step_units: int,
    intervals: int,
    exponent: int,
    precision: int,
) -> None:
    tick = ticks(1, exponent)
    lower, upper = (
        ticks(lower_units, exponent),
        ticks(lower_units + intervals * step_units, exponent),
    )
    with localcontext() as ctx:
        ctx.prec = precision
        plan = build_arithmetic_grid(
            ArithmeticGridSpec(BTCUSDT, Price(lower), Price(upper), intervals), market(tick)
        )
        expected = [Fraction(tick) * (lower_units + i * step_units) for i in range(intervals + 1)]
        assert [Fraction(p.value) for p in plan.prices] == expected
        assert Fraction(plan.step) == Fraction(tick) * step_units
        assert all(a < b for a, b in pairwise(expected))


def test_400_intervals_and_non_decimal_power_tick() -> None:
    tick = Decimal("0.005")
    plan = build_arithmetic_grid(
        ArithmeticGridSpec(BTCUSDT, Price.parse("1"), Price.parse("3"), 400), market(tick)
    )
    assert len(plan.levels) == 401
    assert [Fraction(p.value) for p in plan.prices] == [
        Fraction(1) + i * Fraction(1, 200) for i in range(401)
    ]


def test_nonrepresentable_span_and_out_of_market_bounds_are_rejected() -> None:
    with pytest.raises(DomainError):
        build_arithmetic_grid(
            ArithmeticGridSpec(BTCUSDT, Price.parse("1"), Price.parse("2"), 3),
            market(Decimal("0.01")),
        )
    rules = MarketRules(
        BTCUSDT,
        PriceRules(Price.parse("0.01"), Price.parse("1"), Price.parse("2")),
        QuantityRules(Qty.parse("0.001"), Qty.parse("0.001")),
        NotionalRules(),
    )
    assert build_arithmetic_grid(
        ArithmeticGridSpec(BTCUSDT, Price.parse("1"), Price.parse("2"), 100), rules
    ).step == Decimal("0.01")
    for low, high in (("0.99", "2"), ("1", "2.01")):
        with pytest.raises(DomainError):
            build_arithmetic_grid(
                ArithmeticGridSpec(BTCUSDT, Price.parse(low), Price.parse(high), 1), rules
            )


def test_geometry_beyond_financial_precision_fails_without_rounding() -> None:
    with localcontext() as ctx:
        ctx.prec = 50
        with pytest.raises(DomainError) as caught:
            build_arithmetic_grid(
                ArithmeticGridSpec(BTCUSDT, Price.parse("1e-35"), Price.parse("1"), 1),
                market(Decimal("1e-35")),
            )
        assert caught.value.__cause__ is not None


@settings(max_examples=150, deadline=None, derandomize=True)
@given(st.integers(-(10**65), 10**65), st.integers(-20, 20), st.integers(2, 40))
def test_signed_money_negation_is_exact_involutive_and_immutable(
    units: int, exponent: int, precision: int
) -> None:
    raw = Decimal((int(units < 0), tuple(int(c) for c in str(abs(units))), exponent))
    value = Money(raw, USDT)
    with localcontext() as ctx:
        ctx.prec = precision
        ctx.traps[Inexact] = True
        negative = -value
        assert Fraction(negative.amount) == -Fraction(raw)
        assert (-negative).amount.as_tuple() == raw.as_tuple()
        assert value.amount.as_tuple() == raw.as_tuple()
        assert negative.asset == value.asset


@pytest.mark.parametrize(
    "raw", ["0", "-0", "1e-100", "-1e100", "1.123456789012345678901234567890123"]
)
def test_negation_keeps_exact_representation_and_zero_sign(raw: str) -> None:
    money = Money.parse(raw, USDT)
    assert (-money).amount.as_tuple() == money.amount.copy_negate().as_tuple()
    negative = -money
    assert (-negative).amount.as_tuple() == money.amount.as_tuple()
