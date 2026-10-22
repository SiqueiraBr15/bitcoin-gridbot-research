from __future__ import annotations

from decimal import Decimal, Inexact, localcontext
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gridbot.domain import BTC, USDT, DomainError, FloatNotAllowedError, Money, Price, Qty

# Faixa realista: até 1e12 com 8 casas (precisão de BTC/USDT na Binance).
amounts = st.decimals(
    min_value=0, max_value=Decimal("1e12"), places=8, allow_nan=False, allow_infinity=False
)
signed_amounts = st.decimals(
    min_value=Decimal("-1e12"),
    max_value=Decimal("1e12"),
    places=8,
    allow_nan=False,
    allow_infinity=False,
)
negatives = st.decimals(max_value=0, allow_nan=False, allow_infinity=False).filter(lambda d: d < 0)
non_positives = st.decimals(max_value=0, allow_nan=False, allow_infinity=False)


# ------------------------------------------------------------------ Price


def test_price_accepts_positive_string() -> None:
    assert Price.parse("65000.12").value == Decimal("65000.12")


@pytest.mark.parametrize("raw", ["0", "-0.01", "-65000", "NaN", "Infinity", "abc"])
def test_price_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(DomainError):
        Price.parse(raw)


def test_price_rejects_float_in_parse_and_constructor() -> None:
    with pytest.raises(FloatNotAllowedError):
        Price.parse(cast(Any, 65000.0))
    with pytest.raises(FloatNotAllowedError):
        Price(cast(Any, 65000.0))


@given(non_positives)
def test_price_rejects_every_non_positive_value(value: Decimal) -> None:
    with pytest.raises(DomainError):
        Price(value)


def test_prices_compare_by_value() -> None:
    assert Price.parse("1.0") == Price.parse("1.00")
    assert Price.parse("1") < Price.parse("1.00000001")


def test_notional_is_exact() -> None:
    assert Price.parse("65000.10").notional(Qty.parse("0.00015")) == Decimal("9.750015")


realistic_prices = st.decimals(
    min_value=Decimal("0.00000001"),
    max_value=Decimal("1e7"),
    places=8,
    allow_nan=False,
    allow_infinity=False,
)
realistic_qtys = st.decimals(
    min_value=0, max_value=Decimal("1e9"), places=8, allow_nan=False, allow_infinity=False
)


@given(realistic_prices, realistic_qtys)
def test_notional_is_finite_decimal_equal_to_exact_product(price: Decimal, qty: Decimal) -> None:
    result = Price(price).notional(Qty(qty))
    assert type(result) is Decimal
    assert result.is_finite()
    with localcontext() as ctx:
        ctx.prec = 100
        assert result == price * qty


def test_notional_beyond_precision_fails_closed_instead_of_rounding() -> None:
    # 18 x 18 dígitos significativos = 35 > FINANCIAL_PRECISION (34): erro, não arredondamento.
    huge = Decimal("1000000000.00000001")
    with pytest.raises(Inexact):
        Price(huge).notional(Qty(huge))


# ------------------------------------------------------------------ Qty


@pytest.mark.parametrize("raw", ["-0.00000001", "-1", "NaN", "-Infinity"])
def test_qty_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(DomainError):
        Qty.parse(raw)


def test_qty_zero_is_allowed() -> None:
    assert Qty.zero().is_zero
    assert Qty.parse("0").is_zero


def test_qty_rejects_float() -> None:
    with pytest.raises(FloatNotAllowedError):
        Qty(cast(Any, 0.5))


@given(negatives)
def test_qty_rejects_every_negative_value(value: Decimal) -> None:
    with pytest.raises(DomainError):
        Qty(value)


def test_qty_subtraction_below_zero_is_rejected() -> None:
    with pytest.raises(DomainError):
        _ = Qty.parse("0.001") - Qty.parse("0.002")


@given(amounts, amounts)
def test_qty_add_then_subtract_roundtrips_exactly(a: Decimal, b: Decimal) -> None:
    total = Qty(a) + Qty(b)
    assert type(total.value) is Decimal
    assert total.value.is_finite()
    assert (total - Qty(b)) == Qty(a)


def test_qty_does_not_mix_with_other_types() -> None:
    with pytest.raises(TypeError):
        _ = Qty.parse("1") + cast(Any, Decimal("1"))


# ------------------------------------------------------------------ Money


def test_money_allows_negative_amounts_for_pnl() -> None:
    assert Money.parse("-12.5", USDT).is_negative


def test_money_rejects_float_and_non_finite() -> None:
    with pytest.raises(FloatNotAllowedError):
        Money(cast(Any, 1.5), USDT)
    with pytest.raises(DomainError):
        Money.parse("NaN", USDT)


def test_money_rejects_mixing_assets() -> None:
    with pytest.raises(DomainError):
        _ = Money.parse("1", USDT) + Money.parse("1", BTC)
    with pytest.raises(DomainError):
        _ = Money.parse("1", USDT) - Money.parse("1", BTC)


def test_money_negation_and_zero() -> None:
    assert -Money.parse("2", USDT) == Money.parse("-2", USDT)
    assert Money.zero(BTC) == Money.parse("0", BTC)


@given(signed_amounts, signed_amounts)
def test_money_addition_is_commutative_and_reversible(a: Decimal, b: Decimal) -> None:
    x, y = Money(a, USDT), Money(b, USDT)
    assert x + y == y + x
    assert (x + y) - y == x
    assert type((x + y).amount) is Decimal
