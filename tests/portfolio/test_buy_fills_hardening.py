"""A8.2: hardening do inventário e da contabilidade (achados F1, F2a, F2b, F6, F7 da A8.1)."""

from __future__ import annotations

import dataclasses
from decimal import Decimal, DecimalException
from typing import Any, cast

import pytest

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


def p(raw: str | int) -> Price:
    return Price.parse(raw)


def q(raw: str) -> Qty:
    return Qty.parse(raw)


def _intents() -> tuple[GridBuyIntent, ...]:
    rules = MarketRules(BTCUSDT, PriceRules(p(1)), QuantityRules(q("0.001"), q("0.001")))
    plan = build_arithmetic_grid(ArithmeticGridSpec(BTCUSDT, p(100), p(110), 5), rules)
    state = bootstrap_grid_state(plan, p(105))
    sizing = size_grid_buys(state, rules, Money.parse("10", USDT))
    return build_buy_intents(state, sizing).intents


INTENT, INTENT_1 = _intents()[:2]  # (0,0) 100 x 0.032 ; (1,0) 102 x 0.032


def fill(
    ref: str = "f1",
    qty: str = "0.032",
    price: str = "100",
    fee: str = "0",
    fee_asset: Asset = USDT,
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
        liquidity=LiquidityRole.MAKER,
    )


def expect_error(code: BuyFillErrorCode, fn: Any) -> BuyFillError:
    with pytest.raises(BuyFillError) as excinfo:
        fn()
    assert excinfo.value.code is code
    assert str(code) in str(excinfo.value)
    return excinfo.value


# ------------------------------------------------------------------ regressão obrigatória


def test_mandatory_0_031968_example_is_still_exact() -> None:
    led = BuyFillLedger(INTENT).record(fill(fee="0.000032", fee_asset=BTC))
    assert led.gross_filled_qty == q("0.032")
    assert led.total_base_fee == q("0.000032")
    assert led.net_acquired_base_qty == q("0.031968")
    assert led.net_acquired_base_qty.value == D("0.031968")
    assert led.grid_owned_inventory.net_qty == q("0.031968")


# ------------------------------------------------------------------ F1: GridOwnedInventory


def inventory(**overrides: object) -> GridOwnedInventory:
    fields: dict[str, object] = {
        "symbol": BTCUSDT,
        "cycle_ref": CellCycleRef(0, 0),
        "net_qty": q("0.031968"),
        "fill_refs": ("f1",),
    }
    fields.update(overrides)
    return GridOwnedInventory(**cast(Any, fields))


def test_valid_inventories() -> None:
    assert inventory().net_qty == q("0.031968")
    empty = inventory(net_qty=Qty.zero(), fill_refs=())
    assert empty.fill_refs == ()


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("symbol", "BTCUSDT", TypeError),
        ("cycle_ref", (0, 0), TypeError),
        ("net_qty", D("0.031968"), TypeError),
        ("net_qty", 0.031968, FloatNotAllowedError),
        ("net_qty", "0.031968", TypeError),
        ("fill_refs", ["f1"], TypeError),  # lista mutável
        ("fill_refs", "f1", TypeError),
        ("fill_refs", None, TypeError),
    ],
)
def test_inventory_rejects_invalid_types(field: str, value: object, error: type) -> None:
    with pytest.raises(error):
        inventory(**{field: value})


@pytest.mark.parametrize(
    "refs",
    [
        ("f1", "f1"),  # duplicada
        ("",),  # vazia
        (" f1",),  # espaço à esquerda
        ("f1 ",),  # espaço à direita
        ("x" * 129,),  # longa demais
        (1,),  # não-str
        ("f1", None),
    ],
)
def test_inventory_rejects_invalid_refs(refs: tuple[object, ...]) -> None:
    expect_error(E.INVALID_INVENTORY, lambda: inventory(fill_refs=refs))


def test_inventory_net_and_refs_must_agree() -> None:
    expect_error(E.INVALID_INVENTORY, lambda: inventory(net_qty=q("0.001"), fill_refs=()))
    expect_error(E.INVALID_INVENTORY, lambda: inventory(net_qty=Qty.zero(), fill_refs=("f1",)))


def test_inventory_cannot_hold_negative_or_non_finite_quantity() -> None:
    from gridbot.domain import DomainError

    for raw in ("-0.001", "NaN", "Infinity"):
        with pytest.raises(DomainError):
            inventory(net_qty=Qty.parse(raw))


def test_inventory_is_immutable() -> None:
    inv = inventory()
    with pytest.raises(dataclasses.FrozenInstanceError):
        inv.net_qty = q("1")  # type: ignore[misc]


def test_ledger_projection_always_produces_a_valid_inventory() -> None:
    empty = BuyFillLedger(INTENT)
    assert empty.grid_owned_inventory == GridOwnedInventory(
        BTCUSDT, INTENT.cycle_ref, Qty.zero(), ()
    )
    led = empty.record(fill("f1", "0.010")).record(
        fill("f2", "0.005", fee="0.000005", fee_asset=BTC)
    )
    inv = led.grid_owned_inventory
    assert inv.net_qty == led.net_acquired_base_qty == q("0.014995")
    assert inv.fill_refs == ("f1", "f2")


def test_structurally_valid_inventory_is_not_proof_of_origin() -> None:
    # GRID_OWNED_INVENTORY_IS_A_LEDGER_PROJECTION: refs bem formadas são aceitas mesmo sem
    # existir fill real. Validação estrutural não substitui verificar a origem no ledger.
    forged = inventory(net_qty=q("5"), fill_refs=("made-up",))
    assert forged.net_qty == q("5")
    assert forged != BuyFillLedger(INTENT).grid_owned_inventory


# ------------------------------------------------------- F2a / F2b: limites da deduplicação


def test_economically_identical_fills_with_different_refs_are_distinct_events() -> None:
    # Sem identidade externa confiável, o ledger NÃO detecta que são o mesmo trade.
    led = BuyFillLedger(INTENT).record(fill("trade-A", "0.010")).record(fill("trade-B", "0.010"))
    assert led.gross_filled_qty == q("0.020")
    assert len(led.fills) == 2


def test_same_ref_in_different_ledgers_is_not_detected_locally() -> None:
    # Deduplicação é por ledger; GLOBAL_PERSISTENT_FILL_DEDUPLICATION é requisito futuro.
    a = BuyFillLedger(INTENT).record(fill("shared"))
    b = BuyFillLedger(INTENT_1).record(fill("shared", price="102", cycle=INTENT_1.cycle_ref))
    assert a.has_fills
    assert b.has_fills


# ------------------------------------------------------------------ F7: net_base_qty


@pytest.mark.parametrize(
    ("fee", "asset", "net"),
    [
        ("0.000032", BTC, "0.031968"),
        ("0.0032", USDT, "0.032"),
        ("0.00002", BNB, "0.032"),
        ("0", BTC, "0.032"),
        ("0", USDT, "0.032"),
    ],
)
def test_fill_net_base_qty(fee: str, asset: Asset, net: str) -> None:
    f = fill(fee=fee, fee_asset=asset)
    assert f.net_base_qty == q(net)
    assert f.net_base_qty.value == D(net)
    assert BuyFillLedger(INTENT).record(f).net_acquired_base_qty == f.net_base_qty


def test_fill_net_base_qty_sums_to_ledger_net() -> None:
    fills = [
        fill("f1", "0.010", fee="0.00001", fee_asset=BTC),
        fill("f2", "0.012", fee="0.001", fee_asset=USDT),
        fill("f3", "0.006", fee="0.00003", fee_asset=BNB),
    ]
    led = BuyFillLedger(INTENT)
    for f in fills:
        led = led.record(f)
    total = Qty.zero()
    for f in fills:
        total = total + f.net_base_qty
    assert total == led.net_acquired_base_qty == q("0.02799")


# ------------------------------------------------------------------ construção direta


@pytest.mark.parametrize(
    ("fills", "code"),
    [
        ((fill(symbol=ETHUSDT),), E.SYMBOL_MISMATCH),
        ((fill(cycle=CellCycleRef(0, 1)),), E.CYCLE_MISMATCH),
        ((fill(cycle=CellCycleRef(1, 0)),), E.CYCLE_MISMATCH),
        ((fill(price="100.01"),), E.PRICE_ABOVE_BUY_LIMIT),
        ((fill("f1", "0.020"), fill("f2", "0.013")), E.OVERFILL),
        ((fill("f1", "0.010"), fill("f1", "0.010")), E.INVALID_LEDGER),
        ((fill("f1", "0.010"), fill("f1", "0.011")), E.INVALID_LEDGER),
    ],
    ids=["symbol", "cycle-seq", "cycle-cell", "price", "overfill", "dup-equal", "dup-diff"],
)
def test_direct_construction_cannot_bypass_invariants(
    fills: tuple[ObservedBuyFill, ...], code: BuyFillErrorCode
) -> None:
    expect_error(code, lambda: BuyFillLedger(INTENT, fills))


def test_replace_cannot_bypass_invariants() -> None:
    led = BuyFillLedger(INTENT).record(fill("f1", "0.010"))
    expect_error(E.CYCLE_MISMATCH, lambda: dataclasses.replace(led, intent=INTENT_1))
    expect_error(
        E.OVERFILL, lambda: dataclasses.replace(led, fills=(*led.fills, fill("f2", "0.023")))
    )


# ------------------------------------------------------------------ imutabilidade após erro


@pytest.mark.parametrize(
    ("bad", "code"),
    [
        (fill("f2", "0.023"), E.OVERFILL),
        (fill("f1", "0.011"), E.DUPLICATE_FILL_CONFLICT),
        (fill("f2", "0.001", cycle=CellCycleRef(0, 1)), E.CYCLE_MISMATCH),
        (fill("f2", "0.001", symbol=ETHUSDT), E.SYMBOL_MISMATCH),
        (fill("f2", "0.001", price="100.5"), E.PRICE_ABOVE_BUY_LIMIT),
    ],
)
def test_ledger_is_unchanged_after_rejected_record(
    bad: ObservedBuyFill, code: BuyFillErrorCode
) -> None:
    led = BuyFillLedger(INTENT).record(fill("f1", "0.010", fee="0.00001", fee_asset=BTC))
    snapshot = (dataclasses.astuple(led), led.gross_filled_qty, led.net_acquired_base_qty)
    expect_error(code, lambda: led.record(bad))
    assert (dataclasses.astuple(led), led.gross_filled_qty, led.net_acquired_base_qty) == snapshot


def test_identical_reapply_returns_same_ledger_without_inventory_change() -> None:
    led = BuyFillLedger(INTENT).record(fill("f1", "0.010", fee="0.00001", fee_asset=BTC))
    again = led.record(fill("f1", "0.010", fee="0.00001", fee_asset=BTC))
    assert again is led
    assert again.grid_owned_inventory == led.grid_owned_inventory
    assert again.net_acquired_base_qty == q("0.00999")


def test_decimal_scale_is_economically_equivalent_for_deduplication() -> None:
    led = BuyFillLedger(INTENT).record(fill("f1", "0.010", price="100.00"))
    assert led.record(fill("f1", "0.01", price="100")) is led


def test_zero_third_asset_fee_is_not_unvalued() -> None:
    led = BuyFillLedger(INTENT).record(fill(fee="0", fee_asset=BNB))
    assert led.fees_by_asset == (Money.parse("0", BNB),)
    assert not led.has_unvalued_fees


# ------------------------------------------------------------------ F6: precisão fail-closed


def _assert_precision_error(fn: Any) -> None:
    err = expect_error(E.FINANCIAL_PRECISION_ERROR, fn)
    assert isinstance(err.__cause__, DecimalException)  # exceção original preservada


def test_notional_beyond_precision_fails_closed() -> None:
    f = fill(qty="0.0123456789012345", price="99.99999999999999999999")  # 37 dígitos
    _assert_precision_error(lambda: f.quote_notional)
    led = BuyFillLedger(INTENT).record(f)
    _assert_precision_error(lambda: led.gross_quote_notional)
    _assert_precision_error(lambda: led.quote_debit_total)


def test_executed_qty_sum_beyond_precision_fails_closed() -> None:
    led = BuyFillLedger(INTENT).record(fill("f1", "0.01"))
    _assert_precision_error(lambda: led.record(fill("f2", "1E-40")))
    assert led.gross_filled_qty == q("0.01")  # ledger original intacto


def test_net_subtraction_beyond_precision_fails_closed() -> None:
    f = fill(qty="0.01", fee="1E-40", fee_asset=BTC)
    _assert_precision_error(lambda: f.net_base_qty)
    led = BuyFillLedger(INTENT).record(f)
    _assert_precision_error(lambda: led.net_acquired_base_qty)
    _assert_precision_error(lambda: led.grid_owned_inventory)


def test_fee_sums_beyond_precision_fail_closed() -> None:
    led = (
        BuyFillLedger(INTENT)
        .record(fill("f1", "0.010", fee="1", fee_asset=USDT))
        .record(fill("f2", "0.010", fee="1E-40", fee_asset=USDT))
    )
    _assert_precision_error(lambda: led.quote_fee_total)
    _assert_precision_error(lambda: led.fees_by_asset)
