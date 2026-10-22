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
    LiquidityRole,
    MarketRules,
    Money,
    NotionalRules,
    Price,
    PriceRules,
    Qty,
    QuantityRules,
    RuleViolationCode,
    Symbol,
    is_multiple_of,
)
from gridbot.portfolio import (
    BuyExecutionContext,
    BuyExecutionRef,
    BuyExecutionStatus,
    BuyFillLedger,
    BuyFillReconciliationEvidence,
    FinalizedBuy,
    ObservedBuyFill,
    ObservedBuyTerminalReport,
    SellSizingAssessment,
    SellSizingError,
    SellSizingErrorCode,
    SellSizingStatus,
    assess_sell_sizing,
    finalize_buy,
)
from gridbot.strategy import (
    ArithmeticGridSpec,
    GridBuyIntent,
    GridState,
    bootstrap_grid_state,
    build_arithmetic_grid,
    build_buy_intents,
    size_grid_buys,
)

D = Decimal
E = SellSizingErrorCode
ST = SellSizingStatus
R = RuleViolationCode
BNB = Asset("BNB")
ETHUSDT = Symbol(Asset("ETH"), USDT)


def p(raw: str | int) -> Price:
    return Price.parse(raw)


def q(raw: str) -> Qty:
    return Qty.parse(raw)


def rules(
    *,
    step: str = "0.001",
    tick: str = "1",
    min_qty: str | None = None,
    max_qty: str | None = None,
    min_notional: str | None = None,
    max_notional: str | None = None,
    symbol: Symbol = BTCUSDT,
) -> MarketRules:
    return MarketRules(
        symbol,
        PriceRules(p(tick)),
        QuantityRules(q(step), q(min_qty or step), None if max_qty is None else q(max_qty)),
        NotionalRules.parse(min_notional, max_notional),
    )


def grid(lower: str = "100", upper: str = "110", intervals: int = 5) -> GridState:
    plan = build_arithmetic_grid(
        ArithmeticGridSpec(BTCUSDT, p(lower), p(upper), intervals), rules()
    )
    return bootstrap_grid_state(plan, p(105))


STATE = grid()
_SIZING = size_grid_buys(STATE, rules(), Money.parse("10", USDT))
INTENTS = build_buy_intents(STATE, _SIZING).intents
INTENT = INTENTS[0]  # célula 0: buy 100 / sell 102, qty 0.032
INTENT_2 = INTENTS[2]  # célula 2: buy 104 / sell 106


def fill(
    ref: str, qty: str, fee: str = "0", asset: Asset = USDT, intent: GridBuyIntent = INTENT
) -> ObservedBuyFill:
    return ObservedBuyFill(
        fill_ref=ref,
        cycle_ref=intent.cycle_ref,
        symbol=BTCUSDT,
        execution_price=intent.price,
        executed_qty=q(qty),
        fee=Money.parse(fee, asset),
        liquidity=LiquidityRole.MAKER,
    )


def finalized(*fills: ObservedBuyFill, intent: GridBuyIntent = INTENT) -> FinalizedBuy:
    led = BuyFillLedger(intent)
    for f in fills:
        led = led.record(f)
    status = BuyExecutionStatus.FILLED if led.is_fully_filled else BuyExecutionStatus.CANCELED
    refs = tuple(f.fill_ref for f in led.fills)
    ctx = BuyExecutionContext(intent, BuyExecutionRef(f"exec-{intent.cycle_ref.cell_index}"))
    report = ObservedBuyTerminalReport(
        ctx.execution_ref, BTCUSDT, intent.cycle_ref, status, led.gross_filled_qty, refs
    )
    evidence = BuyFillReconciliationEvidence(
        ctx.execution_ref, BTCUSDT, intent.cycle_ref, led.gross_filled_qty, refs
    )
    return finalize_buy(ctx, led, report, evidence)


def expect_error(code: SellSizingErrorCode, fn: Any) -> SellSizingError:
    with pytest.raises(SellSizingError) as excinfo:
        fn()
    assert excinfo.value.code is code
    assert str(code) in str(excinfo.value)
    return excinfo.value


# ------------------------------------------------------------------ exemplo obrigatório


def test_mandatory_0_031968_example() -> None:
    fin = finalized(fill("t1", "0.032", fee="0.000032", asset=BTC))
    a = assess_sell_sizing(fin, STATE, rules())
    assert a.confirmed_net_qty == q("0.031968")
    assert a.quantized_candidate_qty == q("0.031")
    assert a.step_residual_qty == q("0.000968")
    assert a.quantized_candidate_qty + a.step_residual_qty == a.confirmed_net_qty
    assert a.target_sell_price == p(102)
    assert a.candidate_notional == Money.parse("3.162", USDT)  # não é receita realizada
    assert a.eligibility_status is ST.ELIGIBLE_FOR_SELL_SIZING
    assert a.eligible_sell_qty == q("0.031")
    assert a.market_rule_violations == ()


# ------------------------------------------------------------------ cenários de inventário


def test_fully_filled_buy() -> None:
    a = assess_sell_sizing(finalized(fill("t1", "0.032")), STATE, rules())
    assert a.confirmed_net_qty == q("0.032")
    assert a.quantized_candidate_qty == q("0.032")
    assert a.step_residual_qty == Qty.zero()
    assert a.eligibility_status is ST.ELIGIBLE_FOR_SELL_SIZING


def test_canceled_partial_buy() -> None:
    fin = finalized(fill("t1", "0.010"))
    assert fin.final_status is BuyExecutionStatus.CANCELED
    a = assess_sell_sizing(fin, STATE, rules())
    assert a.quantized_candidate_qty == q("0.010")
    assert a.eligible_sell_qty == q("0.010")


def test_no_fill_is_no_inventory_not_an_error() -> None:
    a = assess_sell_sizing(finalized(), STATE, rules())
    assert a.eligibility_status is ST.NO_INVENTORY
    assert (a.confirmed_net_qty, a.quantized_candidate_qty, a.step_residual_qty) == (
        Qty.zero(),
        Qty.zero(),
        Qty.zero(),
    )
    assert a.eligible_sell_qty is None
    assert a.candidate_notional == Money.parse("0", USDT)


def test_below_step_preserves_whole_inventory() -> None:
    a = assess_sell_sizing(finalized(fill("t1", "0.0008")), STATE, rules())
    assert a.eligibility_status is ST.BELOW_STEP
    assert a.quantized_candidate_qty == Qty.zero()
    assert a.step_residual_qty == q("0.0008")
    assert a.eligible_sell_qty is None
    assert a.market_rule_violations == ()


def test_inventory_equal_to_one_step() -> None:
    a = assess_sell_sizing(finalized(fill("t1", "0.001")), STATE, rules())
    assert a.quantized_candidate_qty == q("0.001")
    assert a.step_residual_qty == Qty.zero()
    assert a.eligibility_status is ST.ELIGIBLE_FOR_SELL_SIZING


def test_inventory_with_residual_and_exactly_aligned() -> None:
    with_residual = assess_sell_sizing(finalized(fill("t1", "0.0155")), STATE, rules())
    assert (with_residual.quantized_candidate_qty, with_residual.step_residual_qty) == (
        q("0.015"),
        q("0.0005"),
    )
    aligned = assess_sell_sizing(finalized(fill("t1", "0.015")), STATE, rules())
    assert aligned.step_residual_qty == Qty.zero()


@pytest.mark.parametrize(
    ("fee", "asset", "net", "candidate"),
    [
        ("0.000032", BTC, "0.031968", "0.031"),  # fee em BTC reduz a candidata
        ("0.0032", USDT, "0.032", "0.032"),  # fee em USDT preserva BTC
        ("0.00002", BNB, "0.032", "0.032"),  # fee em BNB preserva BTC, sem conversão
    ],
)
def test_fee_asset_effect_on_sizing(fee: str, asset: Asset, net: str, candidate: str) -> None:
    a = assess_sell_sizing(finalized(fill("t1", "0.032", fee=fee, asset=asset)), STATE, rules())
    assert a.confirmed_net_qty == q(net)
    assert a.quantized_candidate_qty == q(candidate)


def test_target_price_comes_from_the_buy_cell() -> None:
    fin = finalized(fill("t1", "0.032", intent=INTENT_2), intent=INTENT_2)
    a = assess_sell_sizing(fin, STATE, rules())
    assert a.cell.index == 2
    assert a.target_sell_price == p(106)
    assert a.candidate_notional == Money.parse("3.392", USDT)


# ------------------------------------------------------------------ regras de mercado


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"min_qty": "0.05"}, R.QTY_BELOW_MIN),
        ({"max_qty": "0.01"}, R.QTY_ABOVE_MAX),
        ({"min_notional": "10"}, R.NOTIONAL_BELOW_MIN),
        ({"max_notional": "3"}, R.NOTIONAL_ABOVE_MAX),
        ({"tick": "4"}, R.PRICE_NOT_ALIGNED),  # 102 não é múltiplo de 4
    ],
)
def test_market_rules_block_without_adjusting(
    kwargs: dict[str, str], code: RuleViolationCode
) -> None:
    fin = finalized(fill("t1", "0.032", fee="0.000032", asset=BTC))
    a = assess_sell_sizing(fin, STATE, rules(**cast(Any, kwargs)))
    assert a.eligibility_status is ST.MARKET_RULES_BLOCKED
    assert code in {v.code for v in a.market_rule_violations}
    assert a.eligible_sell_qty is None
    assert a.quantized_candidate_qty == q("0.031")  # nada reduzido, aumentado ou dividido


def test_min_notional_example() -> None:
    a = assess_sell_sizing(finalized(fill("t1", "0.0015")), STATE, rules(min_notional="10"))
    assert a.quantized_candidate_qty == q("0.001")
    assert a.candidate_notional == Money.parse("0.102", USDT)
    assert [v.code for v in a.market_rule_violations] == [R.NOTIONAL_BELOW_MIN]
    assert a.eligible_sell_qty is None
    assert a.confirmed_net_qty == q("0.0015")  # inventário inteiro continua do ciclo


# ------------------------------------------------------------------ vínculo


def test_rules_of_another_symbol_are_rejected() -> None:
    fin = finalized(fill("t1", "0.032"))
    expect_error(E.SYMBOL_MISMATCH, lambda: assess_sell_sizing(fin, STATE, rules(symbol=ETHUSDT)))


def test_advanced_cycle_is_rejected() -> None:
    fin = finalized(fill("t1", "0.032"))
    advanced = STATE.confirm_buy(0).confirm_sell(0)  # célula 0 no ciclo 1
    expect_error(E.CYCLE_MISMATCH, lambda: assess_sell_sizing(fin, advanced, rules()))


def test_unknown_cell_is_rejected() -> None:
    fin = finalized(fill("t1", "0.032", intent=INTENT_2), intent=INTENT_2)
    small = grid("100", "104", 2)  # só células 0 e 1
    expect_error(E.UNKNOWN_CELL, lambda: assess_sell_sizing(fin, small, rules()))


def test_buy_price_incompatible_with_cell_is_rejected() -> None:
    fin = finalized(fill("t1", "0.032"))
    shifted = grid("101", "111", 5)  # célula 0 compra a 101, não a 100
    expect_error(E.BUY_PRICE_MISMATCH, lambda: assess_sell_sizing(fin, shifted, rules()))


def test_waiting_sell_is_not_required_and_state_is_untouched() -> None:
    before = dataclasses.astuple(STATE)
    a = assess_sell_sizing(finalized(fill("t1", "0.032")), STATE, rules())
    assert STATE.cell(0).can_buy  # célula ainda WAITING_BUY: A10 não transita estado
    assert dataclasses.astuple(STATE) == before
    assert a.grid_state is STATE


def test_arbitrary_inventory_or_balance_cannot_be_used() -> None:
    fin = finalized(fill("t1", "0.032"))
    assert list(inspect.signature(assess_sell_sizing).parameters) == [
        "finalized_buy",
        "grid_state",
        "market_rules",
    ]
    with pytest.raises(TypeError):
        assess_sell_sizing(cast(Any, fin.inventory), STATE, rules())
    with pytest.raises(TypeError):
        assess_sell_sizing(cast(Any, q("1")), STATE, rules())


# ------------------------------------------------------------------ pureza / construção


def test_ledger_is_not_debited() -> None:
    fin = finalized(fill("t1", "0.032", fee="0.000032", asset=BTC))
    before = dataclasses.astuple(fin.ledger)
    assess_sell_sizing(fin, STATE, rules())
    assess_sell_sizing(fin, STATE, rules())  # avaliar duas vezes != vender duas vezes
    assert dataclasses.astuple(fin.ledger) == before
    assert fin.net_acquired_base_qty == q("0.031968")


def test_assessment_stores_only_sources() -> None:
    names = {f.name for f in dataclasses.fields(SellSizingAssessment)}
    assert names == {"finalized_buy", "grid_state", "market_rules"}


def test_tampered_direct_construction_is_rejected() -> None:
    a = assess_sell_sizing(finalized(fill("t1", "0.032")), STATE, rules())
    for changes in (
        {"grid_state": STATE.confirm_buy(0).confirm_sell(0)},  # ciclo de outra geração
        {"grid_state": grid("101", "111", 5)},  # preço de outra célula
        {"market_rules": rules(symbol=ETHUSDT)},  # outro símbolo
        {"finalized_buy": cast(Any, finalized(fill("t1", "0.032")).inventory)},
    ):
        with pytest.raises(SellSizingError) as excinfo:
            dataclasses.replace(a, **cast(Any, changes))
        assert excinfo.value.code is E.INVALID_ASSESSMENT
        assert excinfo.value.__cause__ is not None


def test_valid_direct_construction_equals_factory() -> None:
    fin = finalized(fill("t1", "0.032"))
    assert SellSizingAssessment(fin, STATE, rules()) == assess_sell_sizing(fin, STATE, rules())


def test_immutable_and_deterministic() -> None:
    fin = finalized(fill("t1", "0.032", fee="0.000032", asset=BTC))
    a, b = assess_sell_sizing(fin, STATE, rules()), assess_sell_sizing(fin, STATE, rules())
    assert a == b
    assert hash(a) == hash(b)
    assert (a.eligibility_status, a.eligible_sell_qty, a.step_residual_qty) == (
        b.eligibility_status,
        b.eligible_sell_qty,
        b.step_residual_qty,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.market_rules = rules()  # type: ignore[misc]


def test_no_sell_intent_order_or_core_access() -> None:
    a = assess_sell_sizing(finalized(fill("t1", "0.032")), STATE, rules())
    public = {n for n in dir(a) if not n.startswith("_")}
    assert not {n for n in public if "intent" in n.lower() or "order" in n.lower()}
    assert not {n for n in public if "core" in n.lower() or "reserve" in n.lower()}


# ------------------------------------------------------------------ propriedades

STEPS = ["0.00001", "0.0001", "0.001", "0.005"]


@st.composite
def finalized_buys(draw: Any) -> FinalizedBuy:
    units = draw(st.lists(st.integers(min_value=1, max_value=8000), min_size=0, max_size=4))
    fills = []
    total = 0
    for i, n in enumerate(units):
        if total + n > 32000:
            break
        total += n
        qty = D("0.000001") * n
        asset = draw(st.sampled_from([BTC, USDT, BNB]))
        fee = qty * D("0.001") if asset is BTC else D("0.0001")
        fills.append(fill(f"t{i}", str(qty), fee=str(fee), asset=asset))
    return finalized(*fills)


@given(finalized_buys(), st.sampled_from(STEPS), st.sampled_from([None, "0.5", "3", "100"]))
def test_sell_sizing_invariants(fin: FinalizedBuy, step: str, min_notional: str | None) -> None:
    a = assess_sell_sizing(fin, STATE, rules(step=step, min_notional=min_notional))
    net, cand, res, s = a.confirmed_net_qty, a.quantized_candidate_qty, a.step_residual_qty, q(step)
    assert net == fin.ledger.net_acquired_base_qty
    assert cand <= net
    assert cand + res == net
    assert is_multiple_of(cand.value, s.value)
    assert Qty.zero() <= res < s
    if a.eligibility_status is ST.ELIGIBLE_FOR_SELL_SIZING:
        assert a.eligible_sell_qty == cand
        assert a.market_rule_violations == ()
    else:
        assert a.eligible_sell_qty is None
    assert a == assess_sell_sizing(fin, STATE, rules(step=step, min_notional=min_notional))
