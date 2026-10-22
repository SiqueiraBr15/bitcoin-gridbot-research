from __future__ import annotations

import dataclasses
import inspect
from decimal import Decimal
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gridbot.domain import (
    BTCUSDT,
    FloatNotAllowedError,
    GridLevel,
    MarketRules,
    Price,
    PriceRules,
    Qty,
    QuantityRules,
)
from gridbot.strategy import (
    ArithmeticGridPlan,
    ArithmeticGridSpec,
    BootstrapMode,
    CellPhase,
    CellState,
    GridCell,
    GridState,
    GridStateError,
    GridStateErrorCode,
    bootstrap_grid_state,
    build_arithmetic_grid,
    cells_of,
)

D = Decimal
E = GridStateErrorCode
BUY, SELL = CellPhase.WAITING_BUY, CellPhase.WAITING_SELL


def p(raw: str | int) -> Price:
    return Price.parse(raw)


def plan(lower: str = "100", upper: str = "110", intervals: int = 5, tick: str = "1") -> Any:
    rules = MarketRules(
        BTCUSDT, PriceRules(p(tick)), QuantityRules(Qty.parse("0.00001"), Qty.parse("0.00001"))
    )
    return build_arithmetic_grid(ArithmeticGridSpec(BTCUSDT, p(lower), p(upper), intervals), rules)


def snapshot(state: GridState) -> list[tuple[int, CellPhase, bool]]:
    """Só o estado econômico + arming (sem cycle_seq)."""
    return [(c.cell.index, c.phase, c.buy_armed) for c in state.cells]


def cycles(state: GridState) -> list[int]:
    return [c.cycle_seq for c in state.cells]


def expect_error(code: GridStateErrorCode, fn: Any) -> None:
    with pytest.raises(GridStateError) as excinfo:
        fn()
    assert excinfo.value.code is code
    assert str(code) in str(excinfo.value)


# ------------------------------------------------------------------ células


def test_n_intervals_give_n_adjacent_cells() -> None:
    cells = cells_of(plan())
    assert len(cells) == 5
    assert [(c.index, c.buy_price, c.sell_price) for c in cells] == [
        (0, p(100), p(102)),
        (1, p(102), p(104)),
        (2, p(104), p(106)),
        (3, p(106), p(108)),
        (4, p(108), p(110)),
    ]
    for cell in cells:
        assert cell.buy_level.index == cell.index
        assert cell.sell_level.index == cell.index + 1


def test_single_interval_gives_single_cell() -> None:
    (cell,) = cells_of(plan(intervals=1))
    assert (cell.buy_price, cell.sell_price) == (p(100), p(110))


@pytest.mark.parametrize(
    ("index", "buy", "sell"),
    [
        (0, GridLevel(0, p(102)), GridLevel(1, p(100))),  # sell <= buy
        (0, GridLevel(0, p(100)), GridLevel(1, p(100))),
        (1, GridLevel(0, p(100)), GridLevel(1, p(102))),  # índice da célula não bate
        (0, GridLevel(0, p(100)), GridLevel(2, p(104))),  # níveis não adjacentes
        (-1, GridLevel(0, p(100)), GridLevel(1, p(102))),
        (True, GridLevel(0, p(100)), GridLevel(1, p(102))),
    ],
)
def test_invalid_cells_are_rejected(index: object, buy: GridLevel, sell: GridLevel) -> None:
    expect_error(E.INVALID_CELL, lambda: GridCell(cast(Any, index), buy, sell))


def test_cell_has_no_quantity_or_side() -> None:
    assert {f.name for f in dataclasses.fields(GridCell)} == {"index", "buy_level", "sell_level"}
    assert {f.name for f in dataclasses.fields(CellState)} == {
        "cell",
        "phase",
        "buy_armed",
        "cycle_seq",
    }


# ------------------------------------------------------------------ exemplo obrigatório


def test_mandatory_example() -> None:
    initial = bootstrap_grid_state(plan(), p(105))
    assert snapshot(initial) == [
        (0, BUY, True),
        (1, BUY, True),
        (2, BUY, True),
        (3, BUY, False),
        (4, BUY, False),
    ]
    assert initial.waiting_sell_indices == ()

    bought = initial.confirm_buy(2)
    assert snapshot(bought)[2] == (2, SELL, False)
    assert bought.cell(2).holds_grid_owned_inventory
    for i in (0, 1, 3, 4):
        assert bought.cells[i] == initial.cells[i]
        assert bought.cells[i] is initial.cells[i]  # mesmo objeto: nada foi tocado

    sold = bought.confirm_sell(2)
    assert snapshot(sold)[2] == (2, BUY, True)
    for i in (0, 1, 3, 4):
        assert sold.cells[i] == bought.cells[i]
    # A6: ECONOMIC STATE MAY REPEAT, OPERATIONAL IDENTITY MUST NOT.
    # A fase econômica e o arming voltam ao bootstrap, mas a célula 2 está no ciclo 1,
    # então o estado completo NÃO é mais igual ao inicial.
    assert snapshot(sold) == snapshot(initial)
    assert cycles(sold) == [0, 0, 1, 0, 0]
    assert sold != initial


# ------------------------------------------------------------------ bootstrap


@pytest.mark.parametrize(
    ("reference", "armed"),
    [
        ("104", (0, 1)),  # exatamente no buy da célula 2: NÃO arma a célula 2
        ("104.5", (0, 1, 2)),
        ("99", ()),  # abaixo do lower
        ("100", ()),  # igual ao lower
        ("100.01", (0,)),
        ("110", (0, 1, 2, 3, 4)),  # igual ao upper: todos os buys estão abaixo
        ("500", (0, 1, 2, 3, 4)),  # acima do upper
    ],
)
def test_quote_only_arming(reference: str, armed: tuple[int, ...]) -> None:
    state = bootstrap_grid_state(plan(), p(reference))
    assert state.armed_buy_indices == armed
    assert all(c.phase is BUY for c in state.cells)


def test_bootstrap_never_creates_waiting_sell_even_with_levels_above_reference() -> None:
    state = bootstrap_grid_state(plan(), p(101))
    assert state.waiting_sell_indices == ()
    assert not any(c.holds_grid_owned_inventory for c in state.cells)


def test_bootstrap_signature_has_no_balance_or_inventory_input() -> None:
    params = list(inspect.signature(bootstrap_grid_state).parameters)
    assert params == ["plan", "reference_price", "mode"]
    assert inspect.signature(bootstrap_grid_state).parameters["mode"].default is (
        BootstrapMode.QUOTE_ONLY
    )


def test_bootstrap_rejects_bad_inputs() -> None:
    with pytest.raises(FloatNotAllowedError):
        bootstrap_grid_state(plan(), cast(Any, 105.0))
    with pytest.raises(TypeError):
        bootstrap_grid_state(plan(), cast(Any, D("105")))
    with pytest.raises(TypeError):
        bootstrap_grid_state(plan(), p(105), cast(Any, "QUOTE_ONLY"))
    with pytest.raises(TypeError):
        bootstrap_grid_state(cast(Any, "plan"), p(105))


def test_bootstrap_is_deterministic() -> None:
    first = bootstrap_grid_state(plan(), p(105))
    second = bootstrap_grid_state(plan(), p(105))
    assert first == second
    assert hash(first) == hash(second)


# ------------------------------------------------------------------ transições


def test_full_cycle_repeats_without_limit() -> None:
    state = bootstrap_grid_state(plan(), p(105))
    for _ in range(25):
        state = state.confirm_buy(0)
        assert state.cell(0).phase is SELL
        state = state.confirm_sell(0)
        assert state.cell(0).can_buy
    fresh = bootstrap_grid_state(plan(), p(105))
    assert snapshot(state) == snapshot(fresh)  # fase econômica repete...
    assert state.cell(0).cycle_seq == 25  # ...a identidade operacional não
    assert state != fresh


def test_independent_cells_cycle_independently() -> None:
    state = bootstrap_grid_state(plan(), p(110)).confirm_buy(0).confirm_buy(3)
    assert state.waiting_sell_indices == (0, 3)
    assert state.armed_buy_indices == (1, 2, 4)
    state = state.confirm_sell(3)
    assert state.waiting_sell_indices == (0,)


def test_confirm_buy_twice_fails() -> None:
    state = bootstrap_grid_state(plan(), p(105)).confirm_buy(1)
    expect_error(E.NOT_WAITING_BUY, lambda: state.confirm_buy(1))


def test_confirm_sell_before_buy_fails() -> None:
    state = bootstrap_grid_state(plan(), p(105))
    expect_error(E.NOT_WAITING_SELL, lambda: state.confirm_sell(0))


def test_confirm_sell_twice_fails() -> None:
    state = bootstrap_grid_state(plan(), p(105)).confirm_buy(0).confirm_sell(0)
    expect_error(E.NOT_WAITING_SELL, lambda: state.confirm_sell(0))


def test_confirm_buy_on_unarmed_cell_fails() -> None:
    state = bootstrap_grid_state(plan(), p(105))
    expect_error(E.BUY_NOT_ARMED, lambda: state.confirm_buy(3))


@pytest.mark.parametrize("index", [-1, 5, 99])
def test_unknown_cell_index(index: int) -> None:
    state = bootstrap_grid_state(plan(), p(105))
    expect_error(E.UNKNOWN_CELL, lambda: state.confirm_buy(index))
    expect_error(E.UNKNOWN_CELL, lambda: state.confirm_sell(index))


@pytest.mark.parametrize("index", [True, 1.0, "1", None])
def test_non_int_cell_index_is_rejected(index: object) -> None:
    state = bootstrap_grid_state(plan(), p(105))
    with pytest.raises(TypeError):
        state.confirm_buy(cast(Any, index))


def test_failed_transition_leaves_state_untouched() -> None:
    state = bootstrap_grid_state(plan(), p(105))
    before = snapshot(state)
    with pytest.raises(GridStateError):
        state.confirm_buy(4)
    assert snapshot(state) == before


def test_transitions_never_mutate_previous_state() -> None:
    initial = bootstrap_grid_state(plan(), p(105))
    before = snapshot(initial)
    bought = initial.confirm_buy(2)
    bought.confirm_sell(2)
    assert snapshot(initial) == before
    assert bought.cell(2).phase is SELL


# ------------------------------------------------------------------ estado adulterado / imutável


def test_waiting_sell_cannot_be_armed() -> None:
    cell = cells_of(plan())[0]
    expect_error(E.INVALID_STATE, lambda: CellState(cell, SELL, buy_armed=True, cycle_seq=0))


def test_tampered_grid_states_are_rejected() -> None:
    state = bootstrap_grid_state(plan(), p(105))
    other = bootstrap_grid_state(plan("200", "210"), p(205))
    tampered = [
        state.cells[:-1],  # célula faltando
        (*state.cells, state.cells[0]),  # célula extra
        (state.cells[1], state.cells[0], *state.cells[2:]),  # fora de ordem
        (state.cells[0], state.cells[0], *state.cells[2:]),  # duplicada
        (other.cells[0], *state.cells[1:]),  # célula de outro plano
    ]
    for cells in tampered:
        expect_error(E.INVALID_STATE, lambda cells=cells: GridState(state.plan, cells))


def test_cell_state_types_are_enforced() -> None:
    cell = cells_of(plan())[0]
    with pytest.raises(TypeError):
        CellState(cell, cast(Any, "WAITING_BUY"), buy_armed=True, cycle_seq=0)
    with pytest.raises(TypeError):
        CellState(cell, BUY, buy_armed=cast(Any, 1), cycle_seq=0)
    with pytest.raises(TypeError):
        GridState(plan(), cast(Any, list(bootstrap_grid_state(plan(), p(105)).cells)))


def test_everything_is_immutable() -> None:
    state = bootstrap_grid_state(plan(), p(105))
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.cells = ()  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.cells[0].phase = SELL  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.cells[0].cell.index = 9  # type: ignore[misc]


# ------------------------------------------------------------------ propriedades


@given(
    st.integers(min_value=1, max_value=1_000),
    st.integers(min_value=1, max_value=50),
    st.integers(min_value=1, max_value=100),
    st.integers(min_value=1, max_value=10_000),
)
def test_quote_only_bootstrap_rule(
    lower: int, intervals: int, step: int, reference_ticks: int
) -> None:
    grid: ArithmeticGridPlan = plan(str(lower), str(lower + intervals * step), intervals)
    reference = p(reference_ticks)
    state = bootstrap_grid_state(grid, reference)
    assert len(state.cells) == intervals
    assert state.waiting_sell_indices == ()
    assert state.armed_buy_indices == tuple(
        c.index for c in cells_of(grid) if c.buy_price < reference
    )


operations = st.lists(
    st.tuples(st.sampled_from(["buy", "sell"]), st.integers(min_value=-1, max_value=6)),
    max_size=60,
)


@given(st.integers(min_value=99, max_value=111), operations)
def test_state_machine_matches_reference_model(reference: int, ops: list[tuple[str, int]]) -> None:
    state = bootstrap_grid_state(plan(), p(reference))
    model = {i: (BUY, 100 + 2 * i < reference) for i in range(5)}
    model_cycles = dict.fromkeys(range(5), 0)
    for op, index in ops:
        previous = snapshot(state)
        if index not in model:
            expected_error: GridStateErrorCode | None = E.UNKNOWN_CELL
        elif op == "buy":
            phase, armed = model[index]
            expected_error = (
                E.NOT_WAITING_BUY if phase is SELL else (None if armed else E.BUY_NOT_ARMED)
            )
        else:
            expected_error = None if model[index][0] is SELL else E.NOT_WAITING_SELL
        action = state.confirm_buy if op == "buy" else state.confirm_sell
        if expected_error is None:
            state = action(index)
            model[index] = (SELL, False) if op == "buy" else (BUY, True)
            if op == "sell":
                model_cycles[index] += 1  # só a venda confirmada encerra o ciclo
        else:
            expect_error(expected_error, lambda action=action, index=index: action(index))
            assert snapshot(state) == previous
        assert snapshot(state) == [(i, *model[i]) for i in range(5)]
        assert cycles(state) == [model_cycles[i] for i in range(5)]
