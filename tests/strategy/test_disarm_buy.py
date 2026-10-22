"""A11: transição pura ``GridState.disarm_buy``."""

from __future__ import annotations

import dataclasses
from typing import Any, cast

import pytest

from gridbot.domain import BTCUSDT, MarketRules, Price, PriceRules, Qty, QuantityRules
from gridbot.strategy import (
    ArithmeticGridSpec,
    CellPhase,
    GridState,
    GridStateError,
    GridStateErrorCode,
    bootstrap_grid_state,
    build_arithmetic_grid,
)

E = GridStateErrorCode


def state(reference: str = "105") -> GridState:
    rules = MarketRules(
        BTCUSDT,
        PriceRules(Price.parse(1)),
        QuantityRules(Qty.parse("0.001"), Qty.parse("0.001")),
    )
    plan = build_arithmetic_grid(
        ArithmeticGridSpec(BTCUSDT, Price.parse(100), Price.parse(110), 5), rules
    )
    return bootstrap_grid_state(plan, Price.parse(reference))


def test_disarm_keeps_phase_and_cycle_and_other_cells() -> None:
    s = state()
    after = s.disarm_buy(1)
    cell = after.cell(1)
    assert (cell.phase, cell.buy_armed, cell.cycle_seq) == (CellPhase.WAITING_BUY, False, 0)
    assert not cell.can_buy
    for i in (0, 2, 3, 4):
        assert after.cells[i] is s.cells[i]
    assert s.cell(1).buy_armed  # estado original intacto


def test_disarm_preserves_advanced_cycle() -> None:
    s = state().confirm_buy(0).confirm_sell(0)  # ciclo 1, armada
    assert s.disarm_buy(0).cell(0).cycle_seq == 1


def test_disarm_on_waiting_sell_is_rejected() -> None:
    s = state().confirm_buy(0)
    with pytest.raises(GridStateError) as excinfo:
        s.disarm_buy(0)
    assert excinfo.value.code is E.NOT_WAITING_BUY


def test_disarm_on_unarmed_cell_is_rejected() -> None:
    s = state()
    with pytest.raises(GridStateError) as excinfo:
        s.disarm_buy(4)  # buy 108 >= referência 105: não armada
    assert excinfo.value.code is E.BUY_NOT_ARMED


def test_disarm_rejects_unknown_or_invalid_index() -> None:
    with pytest.raises(GridStateError) as excinfo:
        state().disarm_buy(9)
    assert excinfo.value.code is E.UNKNOWN_CELL
    with pytest.raises(TypeError):
        state().disarm_buy(cast(Any, True))


def test_disarmed_cell_cannot_confirm_buy() -> None:
    s = state().disarm_buy(0)
    with pytest.raises(GridStateError) as excinfo:
        s.confirm_buy(0)
    assert excinfo.value.code is E.BUY_NOT_ARMED


def test_disarm_is_deterministic_and_immutable() -> None:
    assert state().disarm_buy(2) == state().disarm_buy(2)
    s = state().disarm_buy(2)
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.cells = ()  # type: ignore[misc]
