from __future__ import annotations

import dataclasses
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gridbot.domain import (
    BTCUSDT,
    USDT,
    Asset,
    MarketRules,
    Money,
    OrderType,
    Price,
    PriceRules,
    Qty,
    QuantityRules,
    Side,
    Symbol,
)
from gridbot.strategy import (
    ArithmeticGridSpec,
    BuyIntentError,
    BuyIntentErrorCode,
    BuyIntentPlan,
    CellCycleRef,
    GridBuyIntent,
    GridSizingError,
    GridSizingPlan,
    GridState,
    GridStateError,
    IntentStaleFinding,
    IntentStaleReason,
    bootstrap_grid_state,
    build_arithmetic_grid,
    build_buy_intents,
    size_grid_buys,
)

E = BuyIntentErrorCode
R = IntentStaleReason
ETHUSDT = Symbol(Asset("ETH"), USDT)


def p(raw: str | int) -> Price:
    return Price.parse(raw)


def q(raw: str) -> Qty:
    return Qty.parse(raw)


def rules(symbol: Symbol = BTCUSDT) -> MarketRules:
    return MarketRules(symbol, PriceRules(p("1")), QuantityRules(q("0.001"), q("0.001")))


def state(
    reference: str = "105", lower: str = "100", upper: str = "110", symbol: Symbol = BTCUSDT
) -> GridState:
    plan = build_arithmetic_grid(ArithmeticGridSpec(symbol, p(lower), p(upper), 5), rules(symbol))
    return bootstrap_grid_state(plan, p(reference))


def size(s: GridState, budget: str = "10") -> GridSizingPlan:
    return size_grid_buys(s, rules(s.plan.spec.symbol), Money.parse(budget, USDT))


def ref(cell: int, cycle: int) -> CellCycleRef:
    return CellCycleRef(cell, cycle)


def expect_error(code: BuyIntentErrorCode, fn: Any) -> BuyIntentError:
    with pytest.raises(BuyIntentError) as excinfo:
        fn()
    assert excinfo.value.code is code
    assert str(code) in str(excinfo.value)
    return excinfo.value


# ------------------------------------------------------------------ exemplo obrigatório


def test_mandatory_example() -> None:
    s = state()
    plan = build_buy_intents(s, size(s))
    assert plan.symbol == BTCUSDT
    assert plan.intents == (
        GridBuyIntent(ref(0, 0), BTCUSDT, p(100), q("0.032")),
        GridBuyIntent(ref(1, 0), BTCUSDT, p(102), q("0.032")),
        GridBuyIntent(ref(2, 0), BTCUSDT, p(104), q("0.032")),
    )
    assert all(i.side is Side.BUY and i.order_type is OrderType.LIMIT for i in plan.intents)
    assert plan.cycle_refs == (ref(0, 0), ref(1, 0), ref(2, 0))


def test_new_cycle_after_buy_and_sell() -> None:
    s0 = state()
    sizing0 = size(s0)
    plan0 = build_buy_intents(s0, sizing0)
    s2 = s0.confirm_buy(2).confirm_sell(2)
    sizing2 = size(s2)
    plan2 = build_buy_intents(s2, sizing2)
    assert plan2.cycle_refs == (ref(0, 0), ref(1, 0), ref(2, 1))
    assert all(i.side is Side.BUY for i in plan2.intents)
    assert plan2.is_current_for(s2, sizing2)
    assert not plan0.is_current_for(s2, sizing2)  # plano antigo stale
    assert not plan0.is_current_for(s2, sizing0)


# ------------------------------------------------------------------ geração


def test_one_intent_per_allocation_in_allocation_order() -> None:
    s = state("110")  # 5 células armadas
    sizing = size(s, "1000")
    plan = build_buy_intents(s, sizing)
    assert len(plan.intents) == len(sizing.allocations) == 5
    for intent, allocation in zip(plan.intents, sizing.allocations, strict=True):
        assert intent.cycle_ref == allocation.cycle_ref
        assert intent.price == allocation.buy_price
        assert intent.qty == allocation.qty
        assert intent.symbol == sizing.symbol


def test_current_empty_sizing_gives_empty_plan() -> None:
    s = state("100")  # nenhuma célula armada
    plan = build_buy_intents(s, size(s))
    assert plan.intents == ()
    assert plan.is_current_for(s, size(s))


def test_intent_has_no_exchange_identity_fee_or_maker_flag() -> None:
    fields = {f.name for f in dataclasses.fields(GridBuyIntent)}
    assert fields == {"cycle_ref", "symbol", "price", "qty", "side", "order_type"}


def test_build_does_not_touch_state_or_sizing() -> None:
    s = state()
    sizing = size(s)
    before_state, before_sizing = dataclasses.astuple(s), dataclasses.astuple(sizing)
    build_buy_intents(s, sizing)
    assert dataclasses.astuple(s) == before_state
    assert dataclasses.astuple(sizing) == before_sizing


def test_build_is_deterministic() -> None:
    s = state()
    a, b = build_buy_intents(s, size(s)), build_buy_intents(s, size(s))
    assert a == b
    assert hash(a) == hash(b)


def test_plan_and_intents_are_immutable() -> None:
    s = state()
    plan = build_buy_intents(s, size(s))
    assert isinstance(plan.intents, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.intents = ()  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.intents[0].price = p(1)  # type: ignore[misc]


# ------------------------------------------------------------------ sizing stale


def test_stale_sizing_after_buy_is_rejected() -> None:
    s0 = state()
    sizing = size(s0)
    err = expect_error(E.STALE_SIZING, lambda: build_buy_intents(s0.confirm_buy(2), sizing))
    assert "NOT_WAITING_BUY(cell 2)" in str(err)


def test_stale_sizing_after_sell_is_rejected() -> None:
    s0 = state()
    sizing = size(s0)
    s2 = s0.confirm_buy(2).confirm_sell(2)
    err = expect_error(E.STALE_SIZING, lambda: build_buy_intents(s2, sizing))
    assert "CYCLE_CHANGED(cell 2)" in str(err)


def test_stale_empty_sizing_is_rejected() -> None:
    empty = size(state("100"))
    expect_error(E.STALE_SIZING, lambda: build_buy_intents(state("101"), empty))


def test_symbol_mismatch_is_rejected() -> None:
    eth = state(symbol=ETHUSDT)
    expect_error(E.SYMBOL_MISMATCH, lambda: build_buy_intents(state(), size(eth)))


def test_build_rejects_raw_types() -> None:
    with pytest.raises(TypeError):
        build_buy_intents(cast(Any, "state"), size(state()))
    with pytest.raises(TypeError):
        build_buy_intents(state(), cast(Any, "sizing"))


# ------------------------------------------------------------------ freshness do plano


def test_fresh_plan_is_current_and_assert_passes() -> None:
    s = state()
    sizing = size(s)
    plan = build_buy_intents(s, sizing)
    freshness = plan.freshness_for(s, sizing)
    assert freshness.current
    assert freshness.sizing_freshness.current
    plan.assert_current_for(s, sizing)


def test_plan_becomes_stale_when_state_changes() -> None:
    s = state()
    sizing = size(s)
    plan = build_buy_intents(s, sizing)
    freshness = plan.freshness_for(s.confirm_buy(0), sizing)
    assert freshness.reasons == (R.SIZING_STALE,)
    with pytest.raises(BuyIntentError) as excinfo:
        plan.assert_current_for(s.confirm_buy(0), sizing)
    assert excinfo.value.code is E.STALE_INTENT_PLAN


def test_plan_is_stale_against_a_different_sizing_qty() -> None:
    s = state()
    plan = build_buy_intents(s, size(s, "10"))  # qty 0.032
    bigger = size(s, "20")  # qty 0.065, mesmos refs
    assert bigger.cycle_refs == plan.cycle_refs
    findings = plan.freshness_for(s, bigger).findings
    assert findings == tuple(IntentStaleFinding(R.QTY_CHANGED, r) for r in plan.cycle_refs)


def test_plan_is_stale_against_shifted_prices() -> None:
    s = state()
    plan = build_buy_intents(s, size(s))
    shifted = state("205", "200", "210")  # mesmos refs, preços diferentes
    findings = plan.freshness_for(shifted, size(shifted, "20")).findings
    assert IntentStaleFinding(R.PRICE_CHANGED, ref(0, 0)) in findings


def test_plan_is_stale_against_other_symbol() -> None:
    s = state()
    plan = build_buy_intents(s, size(s))
    eth = state(symbol=ETHUSDT)
    assert R.SYMBOL_CHANGED in plan.freshness_for(eth, size(eth)).reasons


def test_stale_plan_is_never_regenerated() -> None:
    s = state()
    sizing = size(s)
    plan = build_buy_intents(s, sizing)
    before = dataclasses.astuple(plan)
    plan.freshness_for(s.confirm_buy(1), sizing)
    assert dataclasses.astuple(plan) == before


# ------------------------------------------------------------------ plano adulterado


def _plan() -> BuyIntentPlan:
    s = state()
    return build_buy_intents(s, size(s))


def _with_intents(intents: tuple[GridBuyIntent, ...]) -> BuyIntentPlan:
    return dataclasses.replace(_plan(), intents=intents)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda xs: (dataclasses.replace(xs[0], price=p(99)), *xs[1:]),  # preço adulterado
        lambda xs: (dataclasses.replace(xs[0], qty=q("0.031")), *xs[1:]),  # qty adulterada
        lambda xs: (dataclasses.replace(xs[0], cycle_ref=ref(0, 1)), *xs[1:]),  # ref adulterado
        lambda xs: (dataclasses.replace(xs[0], symbol=ETHUSDT), *xs[1:]),  # símbolo adulterado
        lambda xs: (xs[0], xs[0], xs[2]),  # duplicada
        lambda xs: xs[:2],  # faltante
        lambda xs: (*xs, GridBuyIntent(ref(3, 0), BTCUSDT, p(106), q("0.032"))),  # extra
        lambda xs: (xs[1], xs[0], xs[2]),  # fora de ordem
    ],
    ids=["price", "qty", "cycle-ref", "symbol", "duplicate", "missing", "extra", "order"],
)
def test_tampered_plans_are_rejected(mutate: Any) -> None:
    with pytest.raises(BuyIntentError) as excinfo:
        _with_intents(mutate(_plan().intents))
    assert excinfo.value.code is E.INVALID_PLAN


def test_plan_symbol_must_match_sizing() -> None:
    with pytest.raises(BuyIntentError) as excinfo:
        dataclasses.replace(_plan(), symbol=ETHUSDT)
    assert excinfo.value.code is E.INVALID_PLAN


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"side": Side.SELL}, E.INVALID_INTENT),  # SELL não existe nesta fase
        ({"order_type": OrderType.MARKET}, E.INVALID_INTENT),
        ({"order_type": OrderType.LIMIT_MAKER}, E.INVALID_INTENT),  # post-only não assumido
        ({"qty": Qty.zero()}, E.INVALID_INTENT),
    ],
)
def test_invalid_intents_are_rejected(changes: dict[str, object], code: BuyIntentErrorCode) -> None:
    base = _plan().intents[0]
    with pytest.raises(BuyIntentError) as excinfo:
        dataclasses.replace(base, **cast(Any, changes))
    assert excinfo.value.code is code


def test_intent_types_are_enforced() -> None:
    with pytest.raises(TypeError):
        GridBuyIntent(cast(Any, (0, 0)), BTCUSDT, p(100), q("0.032"))
    with pytest.raises(TypeError):
        GridBuyIntent(ref(0, 0), BTCUSDT, cast(Any, "100"), q("0.032"))
    with pytest.raises(TypeError):
        GridBuyIntent(ref(0, 0), BTCUSDT, p(100), q("0.032"), side=cast(Any, "BUY"))
    with pytest.raises(TypeError):
        dataclasses.replace(_plan(), intents=cast(Any, list(_plan().intents)))


# ------------------------------------------------------------------ propriedades


@given(
    st.integers(min_value=99, max_value=111),
    st.sampled_from(["0", "1", "10", "57.3", "1000"]),
    st.lists(
        st.tuples(st.sampled_from(["buy", "sell"]), st.integers(min_value=0, max_value=4)),
        max_size=30,
    ),
)
def test_intent_plan_properties(reference: int, budget: str, ops: list[tuple[str, int]]) -> None:
    s = state(str(reference))
    for op, index in ops:
        try:
            s = s.confirm_buy(index) if op == "buy" else s.confirm_sell(index)
        except GridStateError:
            continue
    try:
        sizing = size(s, budget)
    except GridSizingError:  # budget insuficiente: nada a planejar
        return
    plan = build_buy_intents(s, sizing)
    assert len(plan.intents) == len(sizing.allocations)
    for intent, allocation in zip(plan.intents, sizing.allocations, strict=True):
        assert intent.cycle_ref == allocation.cycle_ref
        assert intent.price == allocation.buy_price
        assert intent.qty == allocation.qty
        assert intent.side is Side.BUY
        assert intent.order_type is OrderType.LIMIT
    assert plan == build_buy_intents(s, sizing)  # determinismo
    assert plan.is_current_for(s, sizing)
    # Qualquer transição válida numa célula alocada torna o sizing stale e bloqueia o build.
    for index in sizing.cell_indices[:1]:
        moved = s.confirm_buy(index)
        assert not sizing.is_current_for(moved)
        expect_error(E.STALE_SIZING, lambda moved=moved: build_buy_intents(moved, sizing))
        assert not plan.is_current_for(moved, sizing)
