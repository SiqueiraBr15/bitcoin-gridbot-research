"""Intenções puras de compra LIMIT do grid (ADR-015).

STRATEGY INTENT = "a estratégia deseja ter esta ordem". NÃO significa ordem enviada,
aceita, aberta ou executada, nem saldo reservado ou client order id criado. Nenhum side
effect existe aqui.

Fluxo: ``GridState`` + ``GridSizingPlan`` CURRENT -> ``BuyIntentPlan``. Cada alocação
gera exatamente uma ``GridBuyIntent`` (BUY, LIMIT, ``buy_price``, ``qty``), com o mesmo
``CellCycleRef``. Este módulo:

- não recalcula qty nem quantiza preço/qty (a A5 já validou contra ``MarketRules``);
- não consulta preço atual: se uma LIMIT seria "marketable" é decisão da execução;
- não marca MAKER: LIMIT não implica maker, e o papel de liquidez é da execução;
- não cria SELL: venda só nasce de inventário confirmado por fill (futuro);
- não reserva capital e não é idempotente por si: reenvio, retry e client order id
  determinístico pertencem à futura camada de execução.

Um plano stale nunca é atualizado silenciosamente.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from gridbot.domain.assets import Symbol
from gridbot.domain.enums import OrderType, Side
from gridbot.domain.errors import DomainError, FloatNotAllowedError
from gridbot.domain.values import Price, Qty
from gridbot.strategy.grid_sizing import GridSizingPlan, SizingFreshness
from gridbot.strategy.grid_state import CellCycleRef, GridState


class BuyIntentErrorCode(StrEnum):
    SYMBOL_MISMATCH = "SYMBOL_MISMATCH"
    STALE_SIZING = "STALE_SIZING"
    STALE_INTENT_PLAN = "STALE_INTENT_PLAN"
    INVALID_INTENT = "INVALID_INTENT"
    INVALID_PLAN = "INVALID_PLAN"


class BuyIntentError(DomainError):
    """Intenção/plano inválidos ou derivados de sizing/estado stale."""

    def __init__(self, code: BuyIntentErrorCode, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def _expect(value: object, expected: type, field: str) -> None:
    if isinstance(value, float):
        raise FloatNotAllowedError(field)
    if not isinstance(value, expected):
        raise TypeError(f"{field}: esperado {expected.__name__}, recebido {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class GridBuyIntent:
    """Desejo de uma compra LIMIT para uma célula num ciclo. Identidade: ``cycle_ref`` + BUY.

    ``side`` e ``order_type`` são fixos (BUY/LIMIT) e validados; existem como campos para a
    intenção ser autoexplicativa.
    """

    cycle_ref: CellCycleRef
    symbol: Symbol
    price: Price
    qty: Qty
    side: Side = Side.BUY
    order_type: OrderType = OrderType.LIMIT

    def __post_init__(self) -> None:
        _expect(self.cycle_ref, CellCycleRef, "cycle_ref")
        _expect(self.symbol, Symbol, "symbol")
        _expect(self.price, Price, "price")
        _expect(self.qty, Qty, "qty")
        _expect(self.side, Side, "side")
        _expect(self.order_type, OrderType, "order_type")
        if self.side is not Side.BUY:
            raise BuyIntentError(
                BuyIntentErrorCode.INVALID_INTENT, f"{self.cycle_ref}: só BUY nesta fase"
            )
        if self.order_type is not OrderType.LIMIT:
            raise BuyIntentError(
                BuyIntentErrorCode.INVALID_INTENT, f"{self.cycle_ref}: só LIMIT nesta fase"
            )
        if self.qty.is_zero:
            raise BuyIntentError(BuyIntentErrorCode.INVALID_INTENT, f"{self.cycle_ref}: qty 0")


class IntentStaleReason(StrEnum):
    SIZING_STALE = "SIZING_STALE"
    SYMBOL_CHANGED = "SYMBOL_CHANGED"
    INTENTS_CHANGED = "INTENTS_CHANGED"
    PRICE_CHANGED = "PRICE_CHANGED"
    QTY_CHANGED = "QTY_CHANGED"


@dataclass(frozen=True, slots=True)
class IntentStaleFinding:
    reason: IntentStaleReason
    cycle_ref: CellCycleRef | None = None


@dataclass(frozen=True, slots=True)
class IntentPlanFreshness:
    """Diagnóstico de um ``BuyIntentPlan`` frente a ``state`` + ``sizing``."""

    sizing_freshness: SizingFreshness
    findings: tuple[IntentStaleFinding, ...]

    @property
    def current(self) -> bool:
        return not self.findings

    @property
    def reasons(self) -> tuple[IntentStaleReason, ...]:
        return tuple(f.reason for f in self.findings)


def _correspondence_findings(
    intents: tuple[GridBuyIntent, ...], symbol: Symbol, sizing: GridSizingPlan
) -> list[IntentStaleFinding]:
    found: list[IntentStaleFinding] = []
    if symbol != sizing.symbol or any(i.symbol != sizing.symbol for i in intents):
        found.append(IntentStaleFinding(IntentStaleReason.SYMBOL_CHANGED))
    if tuple(i.cycle_ref for i in intents) != sizing.cycle_refs:
        found.append(IntentStaleFinding(IntentStaleReason.INTENTS_CHANGED))
        return found
    for intent, allocation in zip(intents, sizing.allocations, strict=True):
        if intent.price != allocation.buy_price:
            found.append(IntentStaleFinding(IntentStaleReason.PRICE_CHANGED, intent.cycle_ref))
        if intent.qty != allocation.qty:
            found.append(IntentStaleFinding(IntentStaleReason.QTY_CHANGED, intent.cycle_ref))
    return found


@dataclass(frozen=True, slots=True)
class BuyIntentPlan:
    """Intenções de compra derivadas 1:1, na mesma ordem, das alocações de ``sizing``.

    O próprio plano verifica que cada intenção corresponde exatamente à alocação de
    origem (ref, preço, qty, símbolo), então não aceita listas arbitrárias.
    """

    symbol: Symbol
    sizing: GridSizingPlan
    intents: tuple[GridBuyIntent, ...]

    def __post_init__(self) -> None:
        _expect(self.symbol, Symbol, "symbol")
        _expect(self.sizing, GridSizingPlan, "sizing")
        if not isinstance(self.intents, tuple) or not all(
            isinstance(i, GridBuyIntent) for i in self.intents
        ):
            raise TypeError("intents deve ser tuple[GridBuyIntent, ...] (imutável)")
        refs = [i.cycle_ref for i in self.intents]
        if len(set(refs)) != len(refs):
            raise BuyIntentError(BuyIntentErrorCode.INVALID_PLAN, "cycle_ref duplicado")
        mismatches = _correspondence_findings(self.intents, self.symbol, self.sizing)
        if mismatches:
            reasons = ", ".join(f.reason for f in mismatches)
            raise BuyIntentError(
                BuyIntentErrorCode.INVALID_PLAN, f"intenções não correspondem ao sizing ({reasons})"
            )

    @property
    def cycle_refs(self) -> tuple[CellCycleRef, ...]:
        return tuple(i.cycle_ref for i in self.intents)

    def freshness_for(self, state: GridState, sizing: GridSizingPlan) -> IntentPlanFreshness:
        """Current se ``sizing`` é current para ``state`` e as intenções correspondem
        exatamente às alocações de ``sizing``. Não regenera nada."""
        _expect(state, GridState, "state")
        _expect(sizing, GridSizingPlan, "sizing")
        sizing_freshness = sizing.freshness_for(state)
        findings: list[IntentStaleFinding] = []
        if not sizing_freshness.current:
            findings.append(IntentStaleFinding(IntentStaleReason.SIZING_STALE))
        findings.extend(_correspondence_findings(self.intents, self.symbol, sizing))
        return IntentPlanFreshness(sizing_freshness, tuple(findings))

    def is_current_for(self, state: GridState, sizing: GridSizingPlan) -> bool:
        return self.freshness_for(state, sizing).current

    def assert_current_for(self, state: GridState, sizing: GridSizingPlan) -> None:
        freshness = self.freshness_for(state, sizing)
        if not freshness.current:
            detail = ", ".join(
                f.reason if f.cycle_ref is None else f"{f.reason}({f.cycle_ref})"
                for f in freshness.findings
            )
            raise BuyIntentError(BuyIntentErrorCode.STALE_INTENT_PLAN, detail)


def build_buy_intents(state: GridState, sizing: GridSizingPlan) -> BuyIntentPlan:
    """Traduz um sizing CURRENT em intenções BUY LIMIT, sem recalcular nem quantizar.

    Sizing stale é erro (``STALE_SIZING``): não regenera, não altera cycle refs, não ignora
    alocações. Sizing current vazio gera plano vazio válido.
    """
    _expect(state, GridState, "state")
    _expect(sizing, GridSizingPlan, "sizing")
    symbol = state.plan.spec.symbol
    if sizing.symbol != symbol:
        raise BuyIntentError(
            BuyIntentErrorCode.SYMBOL_MISMATCH, f"sizing de {sizing.symbol} para grid de {symbol}"
        )
    freshness = sizing.freshness_for(state)
    if not freshness.current:
        detail = ", ".join(
            f.reason if f.cell_index is None else f"{f.reason}(cell {f.cell_index})"
            for f in freshness.findings
        )
        raise BuyIntentError(BuyIntentErrorCode.STALE_SIZING, detail)
    intents = tuple(
        GridBuyIntent(cycle_ref=a.cycle_ref, symbol=symbol, price=a.buy_price, qty=a.qty)
        for a in sizing.allocations
    )
    return BuyIntentPlan(symbol=symbol, sizing=sizing, intents=intents)
