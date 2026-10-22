from __future__ import annotations

import dataclasses
import inspect
from decimal import Decimal
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gridbot.domain import (
    BTC,
    BTCUSDT,
    USDT,
    Asset,
    FloatNotAllowedError,
    LiquidityRole,
    MarketRules,
    Money,
    Price,
    PriceRules,
    Qty,
    QuantityRules,
    Side,
    Symbol,
)
from gridbot.portfolio import (
    BuyFillError,
    BuyFillErrorCode,
    BuyFillLedger,
    GridOwnedInventory,
    ObservedBuyFill,
)
from gridbot.strategy import (
    ArithmeticGridSpec,
    CellCycleRef,
    GridBuyIntent,
    bootstrap_grid_state,
    build_arithmetic_grid,
    build_buy_intents,
    size_grid_buys,
)

D = Decimal
E = BuyFillErrorCode
BNB = Asset("BNB")
ETHUSDT = Symbol(Asset("ETH"), USDT)
MAKER, TAKER = LiquidityRole.MAKER, LiquidityRole.TAKER


def p(raw: str | int) -> Price:
    return Price.parse(raw)


def q(raw: str) -> Qty:
    return Qty.parse(raw)


def intents() -> tuple[GridBuyIntent, ...]:
    """Intenções reais do pipeline A3->A7: (0,0) 100, (1,0) 102, (2,0) 104, qty 0.032."""
    rules = MarketRules(BTCUSDT, PriceRules(p(1)), QuantityRules(q("0.001"), q("0.001")))
    plan = build_arithmetic_grid(ArithmeticGridSpec(BTCUSDT, p(100), p(110), 5), rules)
    state = bootstrap_grid_state(plan, p(105))
    sizing = size_grid_buys(state, rules, Money.parse("10", USDT))
    return build_buy_intents(state, sizing).intents


INTENT = intents()[0]  # (0,0) BUY LIMIT 100 x 0.032


def fill(
    ref: str = "f1",
    qty: str = "0.032",
    price: str = "100",
    fee: str = "0",
    fee_asset: Asset = USDT,
    liquidity: LiquidityRole = MAKER,
    cycle: CellCycleRef = INTENT.cycle_ref,
    symbol: Symbol = BTCUSDT,
) -> ObservedBuyFill:
    return ObservedBuyFill(
        fill_ref=ref,
        cycle_ref=cycle,
        symbol=symbol,
        execution_price=p(price),
        executed_qty=q(qty),
        fee=Money.parse(fee, fee_asset),
        liquidity=liquidity,
    )


def ledger(*fills: ObservedBuyFill) -> BuyFillLedger:
    result = BuyFillLedger(INTENT)
    for f in fills:
        result = result.record(f)
    return result


def expect_error(code: BuyFillErrorCode, fn: Any) -> BuyFillError:
    with pytest.raises(BuyFillError) as excinfo:
        fn()
    assert excinfo.value.code is code
    assert str(code) in str(excinfo.value)
    return excinfo.value


# ------------------------------------------------------------------ caso obrigatório


def test_base_fee_reduces_inventory_exactly() -> None:
    led = ledger(fill(fee="0.000032", fee_asset=BTC))
    assert led.gross_filled_qty == q("0.032")
    assert led.total_base_fee == q("0.000032")
    assert led.net_acquired_base_qty == q("0.031968")  # exato, não quantizado ao step
    assert led.gross_quote_notional == Money.parse("3.2", USDT)
    assert led.quote_fee_total == Money.parse("0", USDT)
    assert led.quote_debit_total == Money.parse("3.2", USDT)
    assert led.is_fully_filled
    assert not led.is_partially_filled


# ------------------------------------------------------------------ estados de preenchimento


def test_no_fills() -> None:
    led = BuyFillLedger(INTENT)
    assert not led.has_fills
    assert not led.is_partially_filled
    assert not led.is_fully_filled
    assert led.gross_filled_qty == Qty.zero()
    assert led.remaining_qty == q("0.032")
    assert led.net_acquired_base_qty == Qty.zero()
    assert led.fees_by_asset == ()
    assert led.quote_debit_total == Money.parse("0", USDT)


def test_partial_fills() -> None:
    led = ledger(fill("f1", "0.010"), fill("f2", "0.012"))
    assert led.gross_filled_qty == q("0.022")
    assert led.remaining_qty == q("0.010")
    assert led.is_partially_filled
    assert not led.is_fully_filled


def test_multiple_fills_reaching_full() -> None:
    led = ledger(fill("f1", "0.010"), fill("f2", "0.012"), fill("f3", "0.010", price="99.5"))
    assert led.is_fully_filled
    assert led.remaining_qty == Qty.zero()
    assert led.gross_quote_notional == Money.parse("3.1950", USDT)  # 1.0 + 1.2 + 0.995


def test_overfill_is_rejected_not_adjusted() -> None:
    led = ledger(fill("f1", "0.030"))
    expect_error(E.OVERFILL, lambda: led.record(fill("f2", "0.003")))
    assert led.gross_filled_qty == q("0.030")  # ledger original intacto
    expect_error(E.OVERFILL, lambda: ledger(fill("f1", "0.033")))


# ------------------------------------------------------------------ idempotência


def test_identical_duplicate_is_noop() -> None:
    first = ledger(fill("f1", "0.010", fee="0.00001", fee_asset=BTC))
    again = first.record(fill("f1", "0.010", fee="0.00001", fee_asset=BTC))
    assert again is first
    assert again.gross_filled_qty == q("0.010")  # BTC não somado duas vezes


def test_conflicting_duplicate_is_rejected() -> None:
    first = ledger(fill("f1", "0.010"))
    expect_error(E.DUPLICATE_FILL_CONFLICT, lambda: first.record(fill("f1", "0.011")))
    expect_error(E.DUPLICATE_FILL_CONFLICT, lambda: first.record(fill("f1", "0.010", fee="1")))
    expect_error(
        E.DUPLICATE_FILL_CONFLICT, lambda: first.record(fill("f1", "0.010", liquidity=TAKER))
    )


def test_ledger_rejects_repeated_refs_on_direct_construction() -> None:
    f = fill("f1", "0.010")
    expect_error(E.INVALID_LEDGER, lambda: BuyFillLedger(INTENT, (f, f)))


# ------------------------------------------------------------------ fees por ativo


def test_quote_fee_is_extra_cost_not_inventory_reduction() -> None:
    led = ledger(fill(fee="0.0032", fee_asset=USDT))
    assert led.net_acquired_base_qty == q("0.032")
    assert led.total_base_fee == Qty.zero()
    assert led.gross_quote_notional == Money.parse("3.2", USDT)
    assert led.quote_fee_total == Money.parse("0.0032", USDT)
    assert led.quote_debit_total == Money.parse("3.2032", USDT)
    assert not led.has_unvalued_fees


def test_third_asset_fee_is_recorded_unconverted_and_flagged() -> None:
    led = ledger(fill(fee="0.00002", fee_asset=BNB))
    assert led.net_acquired_base_qty == q("0.032")
    assert led.quote_debit_total == Money.parse("3.2", USDT)  # BNB não convertido
    assert led.fees_by_asset == (Money.parse("0.00002", BNB),)
    assert led.unvalued_fees == (Money.parse("0.00002", BNB),)
    assert led.has_unvalued_fees


def test_zero_fee() -> None:
    led = ledger(fill(fee="0", fee_asset=BTC))
    assert led.net_acquired_base_qty == q("0.032")
    assert led.fees_by_asset == (Money.parse("0", BTC),)
    assert not led.has_unvalued_fees


def test_fees_aggregated_by_asset_in_deterministic_order() -> None:
    led = ledger(
        fill("f1", "0.010", fee="0.00001", fee_asset=BTC),
        fill("f2", "0.010", fee="0.001", fee_asset=USDT),
        fill("f3", "0.006", fee="0.00003", fee_asset=BNB),
        fill("f4", "0.006", fee="0.000006", fee_asset=BTC),
    )
    assert led.fees_by_asset == (
        Money.parse("0.00003", BNB),
        Money.parse("0.000016", BTC),
        Money.parse("0.001", USDT),
    )
    assert led.total_base_fee == q("0.000016")
    assert led.net_acquired_base_qty == q("0.031984")
    assert led.quote_fee_total == Money.parse("0.001", USDT)


def test_negative_fee_is_rejected() -> None:
    expect_error(E.INVALID_FEE, lambda: fill(fee="-0.0001", fee_asset=USDT))


def test_base_fee_at_or_above_executed_qty_fails_closed() -> None:
    expect_error(E.INVALID_FEE, lambda: fill(qty="0.010", fee="0.011", fee_asset=BTC))
    expect_error(E.INVALID_FEE, lambda: fill(qty="0.010", fee="0.010", fee_asset=BTC))  # líq. 0


def test_observed_fee_is_never_replaced_by_theoretical_rate() -> None:
    # Taxa "estranha" (0.3%) é a fonte do custo; nada a recalcula pelo FeeSchedule.
    led = ledger(fill(fee="0.0096", fee_asset=USDT, liquidity=TAKER))
    assert led.quote_fee_total == Money.parse("0.0096", USDT)
    assert led.fills[0].liquidity is TAKER  # TAKER não vira MAKER


# ------------------------------------------------------------------ preço limite


def test_price_above_limit_is_rejected() -> None:
    expect_error(E.PRICE_ABOVE_BUY_LIMIT, lambda: ledger(fill(price="100.01")))


@pytest.mark.parametrize("price", ["100", "99.99", "50"])
def test_price_at_or_better_than_limit_is_accepted(price: str) -> None:
    assert ledger(fill(price=price)).is_fully_filled


# ------------------------------------------------------------------ correspondência com a intenção


def test_wrong_symbol_is_rejected() -> None:
    expect_error(E.SYMBOL_MISMATCH, lambda: ledger(fill(symbol=ETHUSDT)))


def test_wrong_cycle_is_rejected() -> None:
    expect_error(E.CYCLE_MISMATCH, lambda: ledger(fill(cycle=CellCycleRef(0, 1))))
    expect_error(E.CYCLE_MISMATCH, lambda: ledger(fill(cycle=CellCycleRef(1, 0))))


# ------------------------------------------------------------------ validação do fill


def test_zero_qty_is_rejected() -> None:
    expect_error(E.INVALID_FILL, lambda: fill(qty="0"))


def test_sell_fill_is_rejected() -> None:
    with pytest.raises(BuyFillError) as excinfo:
        dataclasses.replace(fill(), side=Side.SELL)
    assert excinfo.value.code is E.INVALID_FILL


@pytest.mark.parametrize("ref", ["", " f1", "f1 ", "x" * 129])
def test_invalid_fill_ref(ref: str) -> None:
    expect_error(E.INVALID_FILL, lambda: fill(ref=ref))


def test_float_and_raw_values_are_rejected() -> None:
    base = fill()
    for field in ("execution_price", "executed_qty", "fee"):
        with pytest.raises(FloatNotAllowedError):
            dataclasses.replace(base, **{field: cast(Any, 0.5)})
    with pytest.raises(TypeError):
        dataclasses.replace(base, executed_qty=cast(Any, D("0.032")))
    with pytest.raises(TypeError):
        dataclasses.replace(base, liquidity=cast(Any, "MAKER"))
    with pytest.raises(BuyFillError) as excinfo:  # fill_ref não-str: erro tipado
        dataclasses.replace(base, fill_ref=cast(Any, 1))
    assert excinfo.value.code is E.INVALID_FILL


def test_nan_and_infinity_cannot_reach_the_fill() -> None:
    from gridbot.domain import DomainError

    for raw in ("NaN", "Infinity"):
        with pytest.raises(DomainError):
            fill(qty=raw)
        with pytest.raises(DomainError):
            fill(price=raw)
        with pytest.raises(DomainError):
            fill(fee=raw)


def test_ledger_types_are_enforced() -> None:
    with pytest.raises(TypeError):
        BuyFillLedger(cast(Any, "intent"))
    with pytest.raises(TypeError):
        BuyFillLedger(INTENT, cast(Any, [fill()]))
    with pytest.raises(TypeError):
        BuyFillLedger(INTENT).record(cast(Any, "fill"))


# ------------------------------------------------------------------ inventário / pureza


def test_grid_owned_inventory_is_bound_to_cycle_and_fill_origin() -> None:
    led = ledger(fill("f1", "0.010", fee="0.00001", fee_asset=BTC), fill("f2", "0.012"))
    assert led.grid_owned_inventory == GridOwnedInventory(
        symbol=BTCUSDT,
        cycle_ref=CellCycleRef(0, 0),
        net_qty=q("0.02199"),
        fill_refs=("f1", "f2"),
    )


def test_ledger_has_no_wallet_or_external_inventory_input() -> None:
    assert [f.name for f in dataclasses.fields(BuyFillLedger)] == ["intent", "fills"]
    assert list(inspect.signature(BuyFillLedger.record).parameters) == ["self", "fill"]


def test_fill_has_no_exchange_identity_or_timestamp() -> None:
    names = {f.name for f in dataclasses.fields(ObservedBuyFill)}
    assert names == {
        "fill_ref",
        "cycle_ref",
        "symbol",
        "execution_price",
        "executed_qty",
        "fee",
        "liquidity",
        "side",
    }


def test_ledger_is_immutable_and_record_returns_new_ledger() -> None:
    empty = BuyFillLedger(INTENT)
    one = empty.record(fill("f1", "0.010"))
    assert empty.fills == ()
    assert one is not empty
    with pytest.raises(dataclasses.FrozenInstanceError):
        one.fills = ()  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        one.fills[0].executed_qty = q("1")  # type: ignore[misc]


def test_same_event_sequence_gives_same_ledger() -> None:
    events = [fill("f1", "0.010"), fill("f2", "0.012", fee="0.00001", fee_asset=BTC)]
    assert ledger(*events) == ledger(*events)
    assert hash(ledger(*events)) == hash(ledger(*events))


def test_ledger_never_creates_sell_or_touches_grid_state() -> None:
    led = ledger(fill())
    public = {name for name in dir(led) if not name.startswith("_")}
    assert not {n for n in public if "sell" in n.lower()}
    assert "confirm_buy" not in public
    assert "state" not in public


# ------------------------------------------------------------------ propriedades

FEE_ASSETS = [BTC, USDT, BNB]


@st.composite
def fill_sequences(draw: Any) -> list[ObservedBuyFill]:
    units = draw(st.lists(st.integers(min_value=1, max_value=12), min_size=1, max_size=8))
    fills = []
    for i, n in enumerate(units):
        qty = D("0.001") * n
        asset = draw(st.sampled_from(FEE_ASSETS))
        fee = qty * D("0.001") if asset is BTC else D("0.0001") * draw(st.integers(0, 50))
        price = D(100) - D("0.5") * draw(st.integers(0, 20))
        fills.append(
            ObservedBuyFill(
                fill_ref=f"f{i}",
                cycle_ref=INTENT.cycle_ref,
                symbol=BTCUSDT,
                execution_price=Price(price),
                executed_qty=Qty(qty),
                fee=Money(fee, asset),
                liquidity=draw(st.sampled_from([MAKER, TAKER])),
            )
        )
    return fills


@given(fill_sequences())
def test_ledger_invariants(fills: list[ObservedBuyFill]) -> None:
    led = BuyFillLedger(INTENT)
    for f in fills:
        try:
            led = led.record(f)
        except BuyFillError as err:
            if err.code is not E.OVERFILL:
                raise
            # Overfill nunca altera o ledger e só ocorre se exceder o pretendido.
            assert led.gross_filled_qty.value + f.executed_qty.value > INTENT.qty.value
            continue
        assert led.record(f) is led  # reaplicar fill idêntico não muda nada
    assert led.gross_filled_qty <= led.intended_qty
    assert led.net_acquired_base_qty <= led.gross_filled_qty
    assert led.remaining_qty + led.gross_filled_qty == led.intended_qty
    assert led.quote_debit_total == led.gross_quote_notional + led.quote_fee_total
    assert led.has_fills is (led.gross_filled_qty > Qty.zero())
    if led.has_fills:
        assert led.net_acquired_base_qty > Qty.zero()
    replay = BuyFillLedger(INTENT)
    for f in led.fills:
        replay = replay.record(f)
    assert replay == led  # mesma sequência, mesmo resultado
