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
    Price,
    PriceRules,
    Qty,
    QuantityRules,
    Symbol,
)
from gridbot.strategy import (
    ArithmeticGridSpec,
    CellCycleRef,
    CellPhase,
    CellState,
    GridSizingError,
    GridSizingErrorCode,
    GridSizingPlan,
    GridState,
    GridStateError,
    GridStateErrorCode,
    StaleFinding,
    StaleReason,
    bootstrap_grid_state,
    build_arithmetic_grid,
    cells_of,
    size_grid_buys,
)

BUY, SELL = CellPhase.WAITING_BUY, CellPhase.WAITING_SELL
S = StaleReason
ETHUSDT = Symbol(Asset("ETH"), USDT)


def p(raw: str | int) -> Price:
    return Price.parse(raw)


def usdt(raw: str) -> Money:
    return Money.parse(raw, USDT)


def rules(symbol: Symbol = BTCUSDT) -> MarketRules:
    return MarketRules(
        symbol, PriceRules(p("1")), QuantityRules(Qty.parse("0.001"), Qty.parse("0.001"))
    )


def state(
    reference: str = "105",
    lower: str = "100",
    upper: str = "110",
    intervals: int = 5,
    symbol: Symbol = BTCUSDT,
) -> GridState:
    plan = build_arithmetic_grid(
        ArithmeticGridSpec(symbol, p(lower), p(upper), intervals), rules(symbol)
    )
    return bootstrap_grid_state(plan, p(reference))


def size(s: GridState, budget: str = "100") -> GridSizingPlan:
    return size_grid_buys(s, rules(s.plan.spec.symbol), usdt(budget))


def refs(*pairs: tuple[int, int]) -> tuple[CellCycleRef, ...]:
    return tuple(CellCycleRef(i, c) for i, c in pairs)


# ------------------------------------------------------------------ CellCycleRef


def test_cycle_ref_value_object() -> None:
    ref = CellCycleRef(2, 17)
    assert (ref.cell_index, ref.cycle_seq) == (2, 17)
    assert str(ref) == "cell 2 / cycle 17"
    assert CellCycleRef(2, 0) < CellCycleRef(2, 1) < CellCycleRef(3, 0)
    assert len({CellCycleRef(2, 1), CellCycleRef(2, 1)}) == 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        ref.cycle_seq = 18  # type: ignore[misc]


@pytest.mark.parametrize("bad", [-1, True, False, 1.0, "1", None])
@pytest.mark.parametrize("field", ["cell_index", "cycle_seq"])
def test_cycle_ref_rejects_invalid_values(field: str, bad: object) -> None:
    kwargs: dict[str, object] = {"cell_index": 0, "cycle_seq": 0, field: bad}
    with pytest.raises(GridStateError) as excinfo:
        CellCycleRef(**cast(Any, kwargs))
    assert excinfo.value.code is GridStateErrorCode.INVALID_CYCLE_REF


def test_no_arbitrary_cycle_limit() -> None:
    assert CellCycleRef(0, 10**30).cycle_seq == 10**30


# ------------------------------------------------------------------ cycle_seq no estado


def test_bootstrap_starts_every_cell_at_cycle_zero() -> None:
    for reference in ("99", "105", "500"):  # nenhuma, algumas e todas armadas
        s = state(reference)
        assert [c.cycle_seq for c in s.cells] == [0, 0, 0, 0, 0]
        assert [c.cycle_ref for c in s.cells] == list(refs(*((i, 0) for i in range(5))))


def test_buy_keeps_cycle_and_sell_increments() -> None:
    s = state()
    bought = s.confirm_buy(2)
    assert (bought.cell(2).phase, bought.cell(2).cycle_seq) == (SELL, 0)
    sold = bought.confirm_sell(2)
    assert (sold.cell(2).phase, sold.cell(2).buy_armed, sold.cell(2).cycle_seq) == (BUY, True, 1)
    rebought = sold.confirm_buy(2)
    assert (rebought.cell(2).phase, rebought.cell(2).cycle_seq) == (SELL, 1)
    assert rebought.confirm_sell(2).cell(2).cycle_seq == 2


@pytest.mark.parametrize("cycles", [25, 1_000])
def test_many_cycles(cycles: int) -> None:
    s = state()
    untouched = s.cells[1]
    for _ in range(cycles):
        s = s.confirm_buy(0).confirm_sell(0)
    assert s.cell(0).cycle_seq == cycles
    assert s.cells[1] is untouched  # célula não tocada: mesmo objeto
    assert [c.cycle_seq for c in s.cells[1:]] == [0, 0, 0, 0]


def test_untouched_cells_keep_object_identity_across_transitions() -> None:
    s = state()
    after = s.confirm_buy(2).confirm_sell(2)
    for i in (0, 1, 3, 4):
        assert after.cells[i] is s.cells[i]
    assert after.cells[2] is not s.cells[2]
    assert s.cell(2).cycle_seq == 0  # estado anterior intacto


@pytest.mark.parametrize("bad", [-1, True, 1.0, "0", None])
def test_cell_state_rejects_invalid_cycle_seq(bad: object) -> None:
    cell = cells_of(state().plan)[0]
    with pytest.raises(GridStateError) as excinfo:
        CellState(cell, BUY, buy_armed=True, cycle_seq=cast(Any, bad))
    assert excinfo.value.code is GridStateErrorCode.INVALID_STATE


def test_tampering_cycle_in_grid_state_is_rejected() -> None:
    s = state()
    with pytest.raises(GridStateError):
        dataclasses.replace(s.cells[0], cycle_seq=-1)
    with pytest.raises(GridStateError):  # WAITING_SELL armada continua inválido
        dataclasses.replace(s.cells[0], phase=SELL, cycle_seq=3)


def test_armed_buy_refs() -> None:
    s = state().confirm_buy(1).confirm_sell(1)
    assert s.armed_buy_refs == refs((0, 0), (1, 1), (2, 0))


# ------------------------------------------------------------------ sizing vinculado ao ciclo


def test_mandatory_example() -> None:
    s0 = state()
    sizing0 = size_grid_buys(s0, rules(), usdt("10"))
    assert sizing0.cycle_refs == refs((0, 0), (1, 0), (2, 0))
    assert sizing0.qty_per_cell == Qty.parse("0.032")  # matemática da A5 inalterada
    assert sizing0.allocated_quote == usdt("9.792")
    assert sizing0.unallocated_quote == usdt("0.208")
    assert sizing0.is_current_for(s0)

    s1 = s0.confirm_buy(2)
    assert (s1.cell(2).phase, s1.cell(2).cycle_seq) == (SELL, 0)
    f1 = sizing0.freshness_for(s1)
    assert not f1.current
    assert f1.expected_cycle_refs == refs((0, 0), (1, 0))
    assert f1.actual_cycle_refs == refs((0, 0), (1, 0), (2, 0))
    assert f1.findings == (
        StaleFinding(S.ELIGIBLE_CELLS_CHANGED),
        StaleFinding(S.NOT_WAITING_BUY, 2),
    )

    s2 = s1.confirm_sell(2)
    assert (s2.cell(2).phase, s2.cell(2).buy_armed, s2.cell(2).cycle_seq) == (BUY, True, 1)
    f2 = sizing0.freshness_for(s2)
    assert not f2.current
    assert f2.findings == (
        StaleFinding(S.ELIGIBLE_CELLS_CHANGED),
        StaleFinding(S.CYCLE_CHANGED, 2),
    )

    sizing2 = size_grid_buys(s2, rules(), usdt("10"))
    assert sizing2.cycle_refs == refs((0, 0), (1, 0), (2, 1))
    assert sizing2.is_current_for(s2)
    assert sizing2.qty_per_cell == sizing0.qty_per_cell  # mesmos preços, mesma qty


def test_sizing_uses_current_cycles_without_normalizing() -> None:
    s = state("110")
    for _ in range(3):
        s = s.confirm_buy(2).confirm_sell(2)
    assert size(s).cycle_refs == refs((0, 0), (1, 0), (2, 3), (3, 0), (4, 0))


def test_empty_sizing_current_then_stale() -> None:
    no_buy = state("100")  # nenhuma célula armada
    empty = size(no_buy)
    assert empty.allocations == ()
    assert empty.is_current_for(no_buy)
    gained = state("101")  # célula 0 passa a can_buy
    freshness = empty.freshness_for(gained)
    assert not freshness.current
    assert freshness.findings == (StaleFinding(S.ELIGIBLE_CELLS_CHANGED),)
    assert freshness.expected_cycle_refs == refs((0, 0))


def test_divergent_buy_price_is_stale() -> None:
    sizing = size(state())
    shifted = state("205", "200", "210")  # mesmos índices/ciclos, outros preços
    assert shifted.armed_buy_refs == sizing.cycle_refs
    findings = sizing.freshness_for(shifted).findings
    assert findings == tuple(StaleFinding(S.BUY_PRICE_CHANGED, i) for i in (0, 1, 2))


def test_unknown_cell_is_stale() -> None:
    sizing = size(state("110"))  # 5 células armadas
    smaller = state("110", "100", "104", 2)  # só 2 células
    reasons = sizing.freshness_for(smaller).findings
    assert StaleFinding(S.UNKNOWN_CELL, 2) in reasons
    assert StaleFinding(S.UNKNOWN_CELL, 4) in reasons


def test_other_symbol_is_stale() -> None:
    sizing = size(state())
    eth = state(symbol=ETHUSDT)
    assert S.SYMBOL_CHANGED in sizing.freshness_for(eth).reasons


def test_unarmed_cell_is_stale() -> None:
    sizing = size(state())
    unarmed = state("103")  # células 0 e 1 armadas; 2 não
    assert StaleFinding(S.NOT_ARMED, 2) in sizing.freshness_for(unarmed).findings


def test_assert_current_raises_typed_error_and_never_recalculates() -> None:
    s0 = state()
    sizing = size(s0)
    snapshot = dataclasses.astuple(sizing)
    sizing.assert_current_for(s0)  # current: não levanta
    s1 = s0.confirm_buy(0)
    with pytest.raises(GridSizingError) as excinfo:
        sizing.assert_current_for(s1)
    assert excinfo.value.code is GridSizingErrorCode.STALE_SIZING
    assert "NOT_WAITING_BUY(cell 0)" in str(excinfo.value)
    assert dataclasses.astuple(sizing) == snapshot  # plano antigo intacto
    assert sizing.cycle_refs == refs((0, 0), (1, 0), (2, 0))


def test_freshness_is_deterministic() -> None:
    s = state().confirm_buy(1)
    assert size(state()).freshness_for(s) == size(state()).freshness_for(s)


# ------------------------------------------------------------------ propriedades


@given(st.integers(min_value=0, max_value=4), st.integers(min_value=0, max_value=60))
def test_k_complete_cycles_give_cycle_seq_k(cell: int, k: int) -> None:
    s = state("110")
    for _ in range(k):
        s = s.confirm_buy(cell).confirm_sell(cell)
    assert s.cell(cell).cycle_seq == k
    assert all(c.cycle_seq == 0 for c in s.cells if c.cell.index != cell)


operations = st.lists(
    st.tuples(st.sampled_from(["buy", "sell"]), st.integers(min_value=0, max_value=4)),
    max_size=80,
)


@given(st.integers(min_value=99, max_value=111), operations)
def test_transitions_and_sizing_freshness(reference: int, ops: list[tuple[str, int]]) -> None:
    s = state(str(reference))
    for op, index in ops:
        before = s
        sizing = size(before, "100000")
        assert sizing.is_current_for(before)  # sizing recém-gerado é sempre current
        try:
            s = before.confirm_buy(index) if op == "buy" else before.confirm_sell(index)
        except GridStateError:
            continue
        old_seq, new_seq = before.cell(index).cycle_seq, s.cell(index).cycle_seq
        assert new_seq == (old_seq if op == "buy" else old_seq + 1)
        for i in range(5):
            if i != index:
                assert s.cells[i] is before.cells[i]
        if index in sizing.cell_indices:
            assert not sizing.is_current_for(s)  # transição em célula alocada => stale
