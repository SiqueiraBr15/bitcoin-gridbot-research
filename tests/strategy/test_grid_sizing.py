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
from gridbot.strategy import (
    ArithmeticGridSpec,
    CellAllocation,
    CellCycleRef,
    CellRuleFailure,
    GridSizingError,
    GridSizingErrorCode,
    GridSizingPlan,
    GridState,
    SizingPolicy,
    bootstrap_grid_state,
    build_arithmetic_grid,
    size_grid_buys,
)

D = Decimal
E = GridSizingErrorCode
R = RuleViolationCode


def p(raw: str | int) -> Price:
    return Price.parse(raw)


def usdt(raw: str | int) -> Money:
    return Money.parse(raw, USDT)


def rules(
    step: str = "0.001",
    *,
    min_qty: str | None = None,
    max_qty: str | None = None,
    min_notional: str | None = None,
    max_notional: str | None = None,
    tick: str = "1",
    symbol: Symbol = BTCUSDT,
) -> MarketRules:
    return MarketRules(
        symbol,
        PriceRules(p(tick)),
        QuantityRules(
            Qty.parse(step),
            Qty.parse(min_qty or step),
            None if max_qty is None else Qty.parse(max_qty),
        ),
        NotionalRules.parse(min_notional, max_notional),
    )


def state(
    reference: str = "105", lower: str = "100", upper: str = "110", intervals: int = 5
) -> GridState:
    plan = build_arithmetic_grid(
        ArithmeticGridSpec(BTCUSDT, p(lower), p(upper), intervals), rules()
    )
    return bootstrap_grid_state(plan, p(reference))


def expect_error(code: GridSizingErrorCode, fn: Any) -> GridSizingError:
    with pytest.raises(GridSizingError) as excinfo:
        fn()
    assert excinfo.value.code is code
    assert str(code) in str(excinfo.value)
    return excinfo.value


# ------------------------------------------------------------------ exemplo obrigatório


def test_mandatory_10_usdt_example() -> None:
    plan = size_grid_buys(state(), rules("0.001"), usdt("10"))
    assert plan.policy is SizingPolicy.EQUAL_BASE_QUANTITY
    assert plan.symbol == BTCUSDT
    assert plan.bundle_count == 32  # floor(10 / 0.306)
    assert plan.qty_per_cell == Qty.parse("0.032")
    assert plan.allocations == (
        CellAllocation(CellCycleRef(0, 0), p(100), Qty.parse("0.032"), usdt("3.200")),
        CellAllocation(CellCycleRef(1, 0), p(102), Qty.parse("0.032"), usdt("3.264")),
        CellAllocation(CellCycleRef(2, 0), p(104), Qty.parse("0.032"), usdt("3.328")),
    )
    assert plan.cycle_refs == (CellCycleRef(0, 0), CellCycleRef(1, 0), CellCycleRef(2, 0))
    assert plan.allocated_quote == usdt("9.792")
    assert plan.unallocated_quote == usdt("0.208")
    assert plan.allocated_quote + plan.unallocated_quote == plan.spendable_quote_budget


def test_one_more_step_would_exceed_budget() -> None:
    plan = size_grid_buys(state(), rules("0.001"), usdt("10"))
    one_more = D("0.001") * (100 + 102 + 104)
    assert plan.allocated_quote.amount + one_more > D(10)


def test_exact_fit_leaves_zero_remainder() -> None:
    plan = size_grid_buys(state(), rules("0.001"), usdt("9.792"))
    assert plan.qty_per_cell == Qty.parse("0.032")
    assert plan.unallocated_quote == usdt("0")


# ------------------------------------------------------------------ elegibilidade


def test_only_can_buy_cells_are_sized() -> None:
    s = state("110").confirm_buy(1)  # todas armadas, célula 1 vira WAITING_SELL
    plan = size_grid_buys(s, rules(), usdt("100"))
    assert plan.cell_indices == (0, 2, 3, 4)


def test_unarmed_and_waiting_sell_cells_get_nothing() -> None:
    s = state("105").confirm_buy(0)  # armadas restantes: 1 e 2
    plan = size_grid_buys(s, rules(), usdt("100"))
    assert plan.cell_indices == (1, 2)


@pytest.mark.parametrize("budget", ["0", "250"])
def test_no_armed_cells_gives_valid_empty_plan(budget: str) -> None:
    plan = size_grid_buys(state("100"), rules(), usdt(budget))
    assert plan.allocations == ()
    assert plan.qty_per_cell is None
    assert plan.bundle_count == 0
    assert plan.allocated_quote == usdt("0")
    assert plan.unallocated_quote == usdt(budget)


# ------------------------------------------------------------------ budget


def test_budget_in_base_asset_is_rejected() -> None:
    expect_error(
        E.QUOTE_ASSET_MISMATCH, lambda: size_grid_buys(state(), rules(), Money.parse("1", BTC))
    )


def test_negative_budget_is_rejected() -> None:
    expect_error(E.NEGATIVE_BUDGET, lambda: size_grid_buys(state(), rules(), usdt("-0.01")))


def test_zero_budget_with_armed_cells_is_insufficient() -> None:
    expect_error(E.INSUFFICIENT_BUDGET, lambda: size_grid_buys(state(), rules(), usdt("0")))


def test_budget_below_one_bundle_is_insufficient() -> None:
    err = expect_error(
        E.INSUFFICIENT_BUDGET, lambda: size_grid_buys(state(), rules("0.001"), usdt("0.305"))
    )
    assert "0.306" in str(err)


def test_budget_types_are_enforced() -> None:
    with pytest.raises(FloatNotAllowedError):
        size_grid_buys(state(), rules(), cast(Any, 10.0))
    with pytest.raises(TypeError):
        size_grid_buys(state(), rules(), cast(Any, D("10")))
    with pytest.raises(TypeError):
        size_grid_buys(cast(Any, "state"), rules(), usdt("10"))


def test_rules_for_other_market_are_rejected() -> None:
    eth_rules = rules(symbol=Symbol(Asset("ETH"), USDT))
    expect_error(E.INVALID_STATE, lambda: size_grid_buys(state(), eth_rules, usdt("10")))


# ------------------------------------------------------------------ regras de mercado


def test_min_notional_failure_is_not_auto_fixed() -> None:
    # qty 0.032 > 0, mas célula 0 (3.200) fica abaixo de min_notional 3.25.
    err = expect_error(
        E.CELL_RULE_VIOLATION,
        lambda: size_grid_buys(state(), rules(min_notional="3.25"), usdt("10")),
    )
    assert err.failures == (CellRuleFailure(0, (R.NOTIONAL_BELOW_MIN,)),)


def test_min_notional_failing_every_cell_lists_all_cells() -> None:
    err = expect_error(
        E.CELL_RULE_VIOLATION,
        lambda: size_grid_buys(state(), rules(min_notional="5"), usdt("10")),
    )
    assert [f.cell_index for f in err.failures] == [0, 1, 2]
    assert all(f.codes == (R.NOTIONAL_BELOW_MIN,) for f in err.failures)


def test_min_qty_failure() -> None:
    err = expect_error(
        E.CELL_RULE_VIOLATION,
        lambda: size_grid_buys(state(), rules("0.001", min_qty="0.05"), usdt("10")),
    )
    assert all(R.QTY_BELOW_MIN in f.codes for f in err.failures)
    assert len(err.failures) == 3


def test_max_qty_is_infeasible_not_capped() -> None:
    err = expect_error(
        E.SIZING_INFEASIBLE,
        lambda: size_grid_buys(state(), rules("0.001", max_qty="0.01"), usdt("10")),
    )
    assert all(f.codes == (R.QTY_ABOVE_MAX,) for f in err.failures)


def test_max_notional_is_infeasible_not_capped() -> None:
    err = expect_error(
        E.SIZING_INFEASIBLE,
        lambda: size_grid_buys(state(), rules(max_notional="3.3"), usdt("10")),
    )
    assert err.failures == (CellRuleFailure(2, (R.NOTIONAL_ABOVE_MAX,)),)


def test_inconsistent_price_rules_fail_closed() -> None:
    # Plano gerado com tick 1; regras com tick 10 tornam os preços 102/104 desalinhados.
    err = expect_error(
        E.CELL_RULE_VIOLATION, lambda: size_grid_buys(state(), rules(tick="10"), usdt("10"))
    )
    assert [f.cell_index for f in err.failures] == [1, 2]
    assert all(R.PRICE_NOT_ALIGNED in f.codes for f in err.failures)


# ------------------------------------------------------------------ pureza / imutabilidade


def test_state_is_never_modified() -> None:
    s = state()
    before = (s, s.cells)
    plan = size_grid_buys(s, rules(), usdt("10"))
    assert s.cells is before[1]
    assert s == before[0]
    assert plan.cell_indices == s.armed_buy_indices  # nenhuma transição aconteceu


def test_sizing_is_deterministic() -> None:
    a = size_grid_buys(state(), rules(), usdt("10"))
    b = size_grid_buys(state(), rules(), usdt("10"))
    assert a == b
    assert hash(a) == hash(b)


def test_plan_and_allocations_are_immutable() -> None:
    plan = size_grid_buys(state(), rules(), usdt("10"))
    assert isinstance(plan.allocations, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.allocated_quote = usdt("0")  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.allocations[0].qty = Qty.parse("1")  # type: ignore[misc]


def test_allocation_is_not_an_order() -> None:
    fields = {f.name for f in dataclasses.fields(CellAllocation)}
    assert fields == {"cycle_ref", "buy_price", "qty", "notional"}


def test_sizing_signature_has_no_wallet_or_fees() -> None:
    params = list(inspect.signature(size_grid_buys).parameters)
    assert params == ["state", "rules", "spendable_quote_budget"]


# ------------------------------------------------------------------ plano adulterado


def _valid_plan() -> GridSizingPlan:
    return size_grid_buys(state(), rules(), usdt("10"))


@pytest.mark.parametrize(
    "changes",
    [
        {"unallocated_quote": usdt("0.209")},  # allocated + unallocated != budget
        {"allocated_quote": usdt("9.793")},  # != soma dos notionals
        {"qty_per_cell": Qty.parse("0.031")},  # != bundle_count * step
        {"bundle_count": 31},
        {"bundle_count": -1},
        {"qty_per_cell": None},  # None com alocações
        {"spendable_quote_budget": Money.parse("10", BTC)},  # ativo errado
    ],
)
def test_tampered_plans_are_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(GridSizingError) as excinfo:
        dataclasses.replace(_valid_plan(), **cast(Any, changes))
    assert excinfo.value.code is E.INVALID_PLAN


def test_plan_rejects_budget_overrun_and_inconsistent_allocations() -> None:
    plan = _valid_plan()
    with pytest.raises(GridSizingError):  # gasto maior que o budget
        dataclasses.replace(
            plan, spendable_quote_budget=usdt("9"), unallocated_quote=usdt("-0.792")
        )
    swapped = (plan.allocations[1], plan.allocations[0], plan.allocations[2])
    with pytest.raises(GridSizingError):
        dataclasses.replace(plan, allocations=swapped)
    with pytest.raises(GridSizingError):  # qty diferente numa célula
        dataclasses.replace(
            plan,
            allocations=(
                CellAllocation(CellCycleRef(0, 0), p(100), Qty.parse("0.031"), usdt("3.100")),
                *plan.allocations[1:],
            ),
        )
    with pytest.raises(GridSizingError):  # sem alocações mas com qty
        dataclasses.replace(
            plan, allocations=(), allocated_quote=usdt("0"), unallocated_quote=usdt("10")
        )


@pytest.mark.parametrize(("qty", "notional"), [("0", "0"), ("0.032", "3.201")])
def test_invalid_allocations_are_rejected(qty: str, notional: str) -> None:
    with pytest.raises(GridSizingError):
        CellAllocation(CellCycleRef(0, 0), p(100), Qty.parse(qty), usdt(notional))


def test_allocation_requires_cycle_ref_not_bare_index() -> None:
    with pytest.raises(TypeError):
        CellAllocation(cast(Any, 0), p(100), Qty.parse("0.032"), usdt("3.200"))


# ------------------------------------------------------------------ lucro bruto uniforme


def test_equal_qty_gives_equal_gross_profit_per_cycle_on_arithmetic_grid() -> None:
    s = state("110")  # todas as 5 células armadas
    plan = size_grid_buys(s, rules(), usdt("1000"))
    assert plan.qty_per_cell is not None
    qty = plan.qty_per_cell
    gross = {
        (s.cell(a.cell_index).cell.sell_price.value - a.buy_price.value) * qty.value
        for a in plan.allocations
    }
    assert len(gross) == 1  # mesmo lucro bruto por ciclo, antes de fees


# ------------------------------------------------------------------ propriedades


@given(
    st.integers(min_value=1, max_value=5_000),  # lower
    st.integers(min_value=1, max_value=30),  # intervalos
    st.integers(min_value=1, max_value=200),  # passo em ticks
    st.integers(min_value=0, max_value=1_000_000),  # referência
    st.sampled_from(["0.00001", "0.0001", "0.001", "0.05", "1"]),
    st.decimals(min_value=0, max_value=D("1000000"), places=2, allow_nan=False),
)
def test_sizing_properties(
    lower: int, intervals: int, step_ticks: int, reference: int, step: str, budget: D
) -> None:
    upper = lower + intervals * step_ticks
    grid = build_arithmetic_grid(
        ArithmeticGridSpec(BTCUSDT, p(lower), p(upper), intervals), rules(step)
    )
    s = bootstrap_grid_state(grid, p(max(reference, 1)))
    money = Money(budget, USDT)
    armed = s.armed_buy_indices
    unit = D(step) * sum(s.cell(i).cell.buy_price.value for i in armed)
    if armed and budget < unit:
        # Sem limites mín/máx, a única falha possível é budget insuficiente.
        expect_error(E.INSUFFICIENT_BUDGET, lambda: size_grid_buys(s, rules(step), money))
        return
    plan = size_grid_buys(s, rules(step), money)
    assert plan.allocated_quote.amount <= budget
    assert plan.allocated_quote + plan.unallocated_quote == money
    assert plan.cell_indices == armed
    assert plan == size_grid_buys(s, rules(step), money)  # determinismo
    if not armed:
        assert plan.qty_per_cell is None
        return
    qty = plan.qty_per_cell
    assert qty is not None
    assert not qty.is_zero
    assert is_multiple_of(qty.value, D(step))
    assert {a.qty for a in plan.allocations} == {qty}
    for a in plan.allocations:
        assert a.notional == Money(a.buy_price.value * qty.value, USDT)
    # Floor apertado: mais 1 step em todas as células estouraria o budget.
    assert plan.allocated_quote.amount + unit > budget
