"""Sizing puro das compras do grid: política EQUAL_BASE_QUANTITY (ADR-012).

Todas as células armadas para compra recebem exatamente a mesma quantidade de ativo base,
calculada em unidades inteiras de ``step_size``, sem exceder o orçamento:

    unit_bundle_cost = step_size * (P1 + ... + PN)        # +1 step em TODAS as células
    bundle_count     = floor(budget / unit_bundle_cost)   # divisão inteira exata
    qty_per_cell     = bundle_count * step_size

SPENDABLE_QUOTE_BUDGET_EXCLUDES_FEE_RESERVE: o orçamento é só o capital autorizado para o
NOTIONAL das compras deste plano; não é o saldo da carteira e não inclui reserva para fees
(a reserva pertence à futura camada de execução/capital). Nenhuma fee é calculada aqui.

ALL ARMED BUY CELLS MUST BE FUNDABLE: ou todas as células armadas são financiadas com a
mesma quantidade válida, ou o sizing falha. Nenhuma célula é descartada ou priorizada, e
nenhuma quantidade é reduzida ou aumentada para caber em limites.

Uma ``CellAllocation`` é um plano de compra, não uma ordem: não tem id, status nem fill.
O ``GridState`` nunca é alterado.

Vínculo ao ciclo (ADR-013): cada alocação carrega o ``CellCycleRef`` (célula, ciclo) usado no
cálculo. ``GridSizingPlan.freshness_for(state)`` diz se o plano ainda corresponde exatamente
às células ``can_buy`` atuais; um plano STALE nunca é atualizado silenciosamente.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, DecimalException
from enum import StrEnum
from itertools import pairwise

from gridbot.domain.assets import Symbol
from gridbot.domain.decimals import financial
from gridbot.domain.errors import DomainError, FloatNotAllowedError
from gridbot.domain.rules import MarketRules, RuleViolationCode
from gridbot.domain.values import Money, Price, Qty
from gridbot.strategy.grid_state import CellCycleRef, CellPhase, GridState

_ZERO = Decimal(0)
_MAX_LIMIT_CODES = frozenset(
    {RuleViolationCode.QTY_ABOVE_MAX, RuleViolationCode.NOTIONAL_ABOVE_MAX}
)


class SizingPolicy(StrEnum):
    EQUAL_BASE_QUANTITY = "EQUAL_BASE_QUANTITY"
    """Mesma quantidade de ativo base em todas as células armadas."""


class GridSizingErrorCode(StrEnum):
    INVALID_STATE = "INVALID_STATE"
    QUOTE_ASSET_MISMATCH = "QUOTE_ASSET_MISMATCH"
    NEGATIVE_BUDGET = "NEGATIVE_BUDGET"
    INSUFFICIENT_BUDGET = "INSUFFICIENT_BUDGET"
    CELL_RULE_VIOLATION = "CELL_RULE_VIOLATION"
    SIZING_INFEASIBLE = "SIZING_INFEASIBLE"
    INVALID_PLAN = "INVALID_PLAN"
    STALE_SIZING = "STALE_SIZING"


class StaleReason(StrEnum):
    SYMBOL_CHANGED = "SYMBOL_CHANGED"
    ELIGIBLE_CELLS_CHANGED = "ELIGIBLE_CELLS_CHANGED"
    UNKNOWN_CELL = "UNKNOWN_CELL"
    CYCLE_CHANGED = "CYCLE_CHANGED"
    NOT_WAITING_BUY = "NOT_WAITING_BUY"
    NOT_ARMED = "NOT_ARMED"
    BUY_PRICE_CHANGED = "BUY_PRICE_CHANGED"


@dataclass(frozen=True, slots=True)
class StaleFinding:
    """Um motivo de staleness; ``cell_index`` é ``None`` para motivos do plano inteiro."""

    reason: StaleReason
    cell_index: int | None = None


@dataclass(frozen=True, slots=True)
class SizingFreshness:
    """Diagnóstico de um sizing frente a um estado. ``current`` só sem nenhum achado."""

    expected_cycle_refs: tuple[CellCycleRef, ...]
    actual_cycle_refs: tuple[CellCycleRef, ...]
    findings: tuple[StaleFinding, ...]

    @property
    def current(self) -> bool:
        return not self.findings

    @property
    def reasons(self) -> tuple[StaleReason, ...]:
        return tuple(f.reason for f in self.findings)


@dataclass(frozen=True, slots=True)
class CellRuleFailure:
    """Célula cuja alocação candidata viola regras de mercado, com os códigos exatos."""

    cell_index: int
    codes: tuple[RuleViolationCode, ...]


class GridSizingError(DomainError):
    """Sizing inviável ou entrada inválida; ``failures`` lista células e violações."""

    def __init__(
        self,
        code: GridSizingErrorCode,
        detail: str,
        failures: tuple[CellRuleFailure, ...] = (),
    ) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.failures = failures


def _expect(value: object, expected: type, field: str) -> None:
    if isinstance(value, float):
        raise FloatNotAllowedError(field)
    if not isinstance(value, expected):
        raise TypeError(f"{field}: esperado {expected.__name__}, recebido {type(value).__name__}")


def _invalid(detail: str) -> GridSizingError:
    return GridSizingError(GridSizingErrorCode.INVALID_PLAN, detail)


@dataclass(frozen=True, slots=True)
class CellAllocation:
    """Plano de compra de uma célula NUM CICLO: ``notional == buy_price * qty`` (em quote)."""

    cycle_ref: CellCycleRef
    buy_price: Price
    qty: Qty
    notional: Money

    def __post_init__(self) -> None:
        _expect(self.cycle_ref, CellCycleRef, "cycle_ref")
        _expect(self.buy_price, Price, "buy_price")
        _expect(self.qty, Qty, "qty")
        _expect(self.notional, Money, "notional")
        if self.qty.is_zero:
            raise _invalid(f"{self.cycle_ref}: qty deve ser > 0")
        if self.notional.amount != self.buy_price.notional(self.qty):
            raise _invalid(f"{self.cycle_ref}: notional != buy_price * qty")

    @property
    def cell_index(self) -> int:
        return self.cycle_ref.cell_index


@dataclass(frozen=True, slots=True)
class GridSizingPlan:
    """Resultado auditável do sizing. ``qty_per_cell`` é ``None`` se não houver alocação.

    Invariantes: todos os valores em quote; ``allocated == soma dos notionals``;
    ``allocated + unallocated == budget``; ``0 <= allocated <= budget``; todas as alocações
    com a mesma qty, igual a ``bundle_count * step_size``; células em ordem crescente.
    """

    symbol: Symbol
    policy: SizingPolicy
    step_size: Qty
    spendable_quote_budget: Money
    bundle_count: int
    qty_per_cell: Qty | None
    allocations: tuple[CellAllocation, ...]
    allocated_quote: Money
    unallocated_quote: Money

    def __post_init__(self) -> None:
        _expect(self.symbol, Symbol, "symbol")
        _expect(self.policy, SizingPolicy, "policy")
        _expect(self.step_size, Qty, "step_size")
        for name in ("spendable_quote_budget", "allocated_quote", "unallocated_quote"):
            money = getattr(self, name)
            _expect(money, Money, name)
            if money.asset != self.symbol.quote:
                raise _invalid(f"{name} deve estar em {self.symbol.quote}")
        if not isinstance(self.allocations, tuple) or not all(
            isinstance(a, CellAllocation) for a in self.allocations
        ):
            raise TypeError("allocations deve ser tuple[CellAllocation, ...] (imutável)")
        self._check_quantities()
        self._check_amounts()

    def _check_quantities(self) -> None:
        count = self.bundle_count
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise _invalid(f"bundle_count inválido: {count!r}")
        if not self.allocations:
            if self.qty_per_cell is not None:
                raise _invalid("sem alocações, qty_per_cell deve ser None")
            return
        with financial():
            expected_qty = Qty(self.step_size.value * count)
        if self.qty_per_cell != expected_qty:
            raise _invalid("qty_per_cell deve ser bundle_count * step_size")
        if any(a.qty != self.qty_per_cell for a in self.allocations):
            raise _invalid("todas as alocações devem ter a mesma qty")
        if any(a.notional.asset != self.symbol.quote for a in self.allocations):
            raise _invalid(f"notional das alocações deve estar em {self.symbol.quote}")
        if any(b.cell_index <= a.cell_index for a, b in pairwise(self.allocations)):
            raise _invalid("células devem ser únicas e em ordem crescente")

    def _check_amounts(self) -> None:
        total = Money.zero(self.symbol.quote)
        for allocation in self.allocations:
            total = total + allocation.notional
        if self.allocated_quote != total:
            raise _invalid("allocated_quote deve ser a soma dos notionals")
        if self.allocated_quote + self.unallocated_quote != self.spendable_quote_budget:
            raise _invalid("allocated + unallocated deve ser igual ao budget")
        if self.allocated_quote.is_negative or self.unallocated_quote.is_negative:
            raise _invalid("allocated_quote excede o budget")

    @property
    def cell_indices(self) -> tuple[int, ...]:
        return tuple(a.cell_index for a in self.allocations)

    @property
    def cycle_refs(self) -> tuple[CellCycleRef, ...]:
        return tuple(a.cycle_ref for a in self.allocations)

    def freshness_for(self, state: GridState) -> SizingFreshness:
        """Compara o plano com as células ``can_buy`` atuais de ``state``. Não recalcula.

        Current exige: mesmo símbolo; ``cycle_refs`` iguais (conjunto e ordem) aos
        ``state.armed_buy_refs``; e cada alocação ainda em célula existente, no mesmo ciclo,
        WAITING_BUY, armada e com o mesmo ``buy_price``. Um plano vazio fica stale se o
        estado ganhar células elegíveis.
        """
        _expect(state, GridState, "state")
        expected = state.armed_buy_refs
        actual = self.cycle_refs
        findings: list[StaleFinding] = []
        if state.plan.spec.symbol != self.symbol:
            findings.append(StaleFinding(StaleReason.SYMBOL_CHANGED))
        if actual != expected:
            findings.append(StaleFinding(StaleReason.ELIGIBLE_CELLS_CHANGED))
        for allocation in self.allocations:
            findings.extend(_allocation_findings(allocation, state))
        return SizingFreshness(expected, actual, tuple(findings))

    def is_current_for(self, state: GridState) -> bool:
        return self.freshness_for(state).current

    def assert_current_for(self, state: GridState) -> None:
        freshness = self.freshness_for(state)
        if not freshness.current:
            detail = ", ".join(
                f.reason if f.cell_index is None else f"{f.reason}(cell {f.cell_index})"
                for f in freshness.findings
            )
            raise GridSizingError(GridSizingErrorCode.STALE_SIZING, detail)


def _allocation_findings(allocation: CellAllocation, state: GridState) -> list[StaleFinding]:
    index = allocation.cell_index
    if index >= len(state.cells):
        return [StaleFinding(StaleReason.UNKNOWN_CELL, index)]
    cell_state = state.cells[index]
    found = []
    if cell_state.cycle_seq != allocation.cycle_ref.cycle_seq:
        found.append(StaleFinding(StaleReason.CYCLE_CHANGED, index))
    if cell_state.phase is not CellPhase.WAITING_BUY:
        found.append(StaleFinding(StaleReason.NOT_WAITING_BUY, index))
    elif not cell_state.buy_armed:
        found.append(StaleFinding(StaleReason.NOT_ARMED, index))
    if cell_state.cell.buy_price != allocation.buy_price:
        found.append(StaleFinding(StaleReason.BUY_PRICE_CHANGED, index))
    return found


def size_grid_buys(
    state: GridState,
    rules: MarketRules,
    spendable_quote_budget: Money,
) -> GridSizingPlan:
    """Dimensiona as compras das células ``can_buy`` com EQUAL_BASE_QUANTITY.

    Não lê carteira, não calcula fee, não cria ordens e não altera ``state``.
    """
    _expect(state, GridState, "state")
    _expect(rules, MarketRules, "rules")
    _expect(spendable_quote_budget, Money, "spendable_quote_budget")
    symbol = state.plan.spec.symbol
    if rules.symbol != symbol:
        raise GridSizingError(
            GridSizingErrorCode.INVALID_STATE, f"regras de {rules.symbol} para grid de {symbol}"
        )
    budget = spendable_quote_budget
    if budget.asset != symbol.quote:
        raise GridSizingError(
            GridSizingErrorCode.QUOTE_ASSET_MISMATCH,
            f"budget em {budget.asset}; o grid {symbol} exige {symbol.quote}",
        )
    if budget.is_negative:
        raise GridSizingError(GridSizingErrorCode.NEGATIVE_BUDGET, f"budget {budget} < 0")

    step = rules.quantity.step_size
    armed = [cell_state for cell_state in state.cells if cell_state.can_buy]
    if not armed:
        return GridSizingPlan(
            symbol=symbol,
            policy=SizingPolicy.EQUAL_BASE_QUANTITY,
            step_size=step,
            spendable_quote_budget=budget,
            bundle_count=0,
            qty_per_cell=None,
            allocations=(),
            allocated_quote=Money.zero(symbol.quote),
            unallocated_quote=budget,
        )

    try:
        with financial():
            unit_bundle_cost = step.value * sum((c.cell.buy_price.value for c in armed), _ZERO)
            bundle_count = int(budget.amount // unit_bundle_cost)  # floor exato (ambos >= 0)
    except DecimalException as exc:
        raise GridSizingError(
            GridSizingErrorCode.SIZING_INFEASIBLE,
            "orçamento/custo fora da precisão financeira; nenhum arredondamento feito",
        ) from exc
    if bundle_count == 0:
        raise GridSizingError(
            GridSizingErrorCode.INSUFFICIENT_BUDGET,
            f"budget {budget} < custo de 1 step em {len(armed)} células "
            f"({unit_bundle_cost} {symbol.quote})",
        )

    with financial():
        qty = Qty(step.value * bundle_count)
    failures = []
    allocations = []
    for cell_state in armed:
        buy_price = cell_state.cell.buy_price
        check = rules.check(symbol, buy_price, qty)
        if check.ok:
            allocations.append(CellAllocation(cell_state.cycle_ref, buy_price, qty, check.notional))
        else:
            failures.append(CellRuleFailure(cell_state.cell.index, check.codes))
    if failures:
        hits_max = any(set(f.codes) & _MAX_LIMIT_CODES for f in failures)
        code = (
            GridSizingErrorCode.SIZING_INFEASIBLE
            if hits_max
            else GridSizingErrorCode.CELL_RULE_VIOLATION
        )
        detail = "; ".join(f"célula {f.cell_index}: {', '.join(f.codes)}" for f in failures)
        raise GridSizingError(
            code, f"qty {qty} inviável para todas as células ({detail})", tuple(failures)
        )

    allocated = Money.zero(symbol.quote)
    for allocation in allocations:
        allocated = allocated + allocation.notional
    return GridSizingPlan(
        symbol=symbol,
        policy=SizingPolicy.EQUAL_BASE_QUANTITY,
        step_size=step,
        spendable_quote_budget=budget,
        bundle_count=bundle_count,
        qty_per_cell=qty,
        allocations=tuple(allocations),
        allocated_quote=allocated,
        unallocated_quote=budget - allocated,
    )
