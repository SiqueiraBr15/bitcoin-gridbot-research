"""Independent integer/Fraction enumeration of partial allocation admission."""

from dataclasses import replace
from decimal import Decimal
from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gridbot.domain import BTC, BTCUSDT, USDT, Asset, Money, NotionalRules, Price, Qty
from gridbot.paper.accounting import PaperError
from gridbot.paper.partial_allocation import (
    BuyCommitment,
    PartialAllocationInput,
    PartialCosts,
    allocate_partial,
)
from gridbot.strategy import ArithmeticGridSpec, bootstrap_grid_state, build_arithmetic_grid
from tests.backtest.fixtures import rules


def allocation_input(cash: int = 20, base: str = "0") -> PartialAllocationInput:
    market = rules()
    grid = build_arithmetic_grid(
        ArithmeticGridSpec(BTCUSDT, Price.parse("90"), Price.parse("110"), 4), market
    )
    return PartialAllocationInput(
        bootstrap_grid_state(grid, Price.parse("100")),
        market,
        Money(Decimal(cash), USDT),
        Money.zero(USDT),
        Qty.parse(base),
        Qty.zero(),
        Price.parse("100"),
        Money(Decimal(cash), USDT),
        PartialCosts(Decimal(".001"), USDT),
    )


@pytest.mark.parametrize("asset", [BTC, USDT])
@given(cash=st.integers(0, 50), millibtc=st.integers(0, 500))
def test_fraction_enumerates_maximum_prefix_and_quantity(
    asset: Asset, cash: int, millibtc: int
) -> None:
    source = allocation_input(cash)
    source = replace(
        source,
        grid_base=Qty(Decimal(millibtc) / Decimal(1000)),
        costs=PartialCosts(Decimal(".001"), asset),
    )
    result = allocate_partial(source)
    m, step, rate = Fraction(100), Fraction(1, 1000), Fraction(1, 1000)
    legacy = Fraction(millibtc, 1000) * m
    nav, expected = Fraction(cash) + legacy, None
    for prices in ((95, 90), (95,)):
        fits = []
        for units in range(1, 557):
            q = units * step
            fee = q * (sum(prices) if asset == USDT else len(prices) * m) * rate
            quote_fee = fee if asset == USDT else Fraction(0)
            notional = q * sum(prices)
            n, d = legacy + len(prices) * q * m, nav - fee
            filters = all(p * q >= 1 for p in prices)
            if (
                filters
                and notional + quote_fee <= cash
                and notional <= cash
                and n <= Fraction(9, 10) * d
            ):
                fits.append(q)
        if fits:
            expected = prices, max(fits)
            break
    if expected is None:
        assert not result.admissible
    else:
        assert result.admissible
        assert result.plan is not None
        assert (
            tuple(sorted((int(i.price.value) for i in result.plan.intents), reverse=True))
            == expected[0]
        )
        assert all(Fraction(i.qty.value) == expected[1] for i in result.plan.intents)
        assert result.required_quote.amount <= cash
        assert Fraction(result.exposure_numerator.amount) <= Fraction(9, 10) * Fraction(
            result.exposure_denominator.amount
        )


def test_inactive_levels_have_no_intent_or_imaginary_reservation() -> None:
    source = replace(
        allocation_input(2), rules=replace(rules(), notional=NotionalRules.parse("1.5"))
    )
    result = allocate_partial(source)
    assert result.admissible
    assert result.plan is not None
    assert len(result.plan.intents) == 1
    assert result.plan.intents[0].cycle_ref.cell_index == 1
    assert not result.state.cells[0].buy_armed
    assert result.required_quote.amount <= 2
    assert source.state.cells[0].buy_armed


def test_existing_holds_count_once_and_cannot_be_free_funding() -> None:
    source = allocation_input(20)
    commitment = BuyCommitment(
        Price.parse("90"), Qty.parse(".1"), Money.parse(".01", USDT), Qty.zero()
    )
    source = replace(source, buy_reservations=commitment.total_quote, commitments=(commitment,))
    result = allocate_partial(source)
    assert result.plan is not None
    assert result.required_quote.amount <= 20
    assert result.projected_gross_base.value == Decimal(".1") + sum(
        i.qty.value for i in result.plan.intents
    )
    assert all(i.qty == Qty.parse(".080") for i in result.plan.intents)
    bought = sum((Fraction(i.qty.value) for i in result.plan.intents), Fraction())
    fees = sum((Fraction(f.amount) for f in result.fees), Fraction())
    # R=9.01 is capital already held, not extra cash. Its BUY can execute too.
    assert (Fraction(".1") + bought) * 100 <= Fraction(9, 10) * (
        Fraction(20) + Fraction("9.01") - Fraction(".01") - fees
    )
    with pytest.raises(PaperError, match="inventory incomplete"):
        replace(source, commitments=())


@pytest.mark.parametrize(("asset", "third"), [(Asset("BNB"), False), (USDT, True)])
def test_third_assets_require_complete_valuation(asset: Asset, third: bool) -> None:
    result = allocate_partial(
        replace(
            allocation_input(),
            costs=PartialCosts(Decimal(".001"), asset),
            third_assets_present=third,
        )
    )
    assert result.blockers == ("THIRD_ASSET_VALUATION_REQUIRED",)
    assert not result.admissible


def test_passive_exposure_blocks_buy_without_changing_inventory() -> None:
    source = allocation_input(1, "1")
    result = allocate_partial(source)
    assert result.blockers == ("GLOBAL_EXPOSURE_HEADROOM_EXHAUSTED",)
    assert result.projected_gross_base == source.grid_base


def test_limits_filter_quantities_before_publication() -> None:
    source = allocation_input()
    market = replace(
        source.rules, quantity=replace(source.rules.quantity, max_qty=Qty.parse(".02"))
    )
    result = allocate_partial(replace(source, rules=market))
    assert result.plan is not None
    assert all(i.qty <= Qty.parse(".02") for i in result.plan.intents)
    assert all(market.check(BTCUSDT, i.price, i.qty).ok for i in result.plan.intents)


def test_max_notional_is_enforced_before_sizing_not_as_silent_truncation() -> None:
    source = allocation_input()
    market = replace(source.rules, notional=NotionalRules.parse("1", "1.9"))
    result = allocate_partial(replace(source, rules=market))
    assert result.plan is not None
    assert all(i.qty == Qty.parse(".020") for i in result.plan.intents)
    assert all(i.price.notional(i.qty) <= Decimal("1.9") for i in result.plan.intents)


@pytest.mark.parametrize("rate", ["-0.1", "1", "NaN", "Infinity"])
def test_invalid_fees_fail_closed(rate: str) -> None:
    with pytest.raises((PaperError, ValueError)):
        PartialCosts(Decimal(rate), USDT)


def test_sell_reservation_is_not_additional_btc() -> None:
    source = allocation_input(20, ".01")
    left = allocate_partial(source)
    right = allocate_partial(replace(source, sell_reservations=source.grid_base))
    assert left.exposure_numerator == right.exposure_numerator
    assert left.exposure_denominator == right.exposure_denominator
