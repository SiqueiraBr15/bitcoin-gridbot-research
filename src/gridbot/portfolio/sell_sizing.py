"""Dimensionamento puro de venda e preservação do residual (ADR-018).

``FinalizedBuy`` + ``GridState`` + ``MarketRules`` -> ``SellSizingAssessment``.

SELL_SIZING_ELIGIBLE != SELL_ORDER_AUTHORIZED: o resultado é só uma avaliação matemática.
Nenhuma ordem, reserva, débito de inventário, fee de venda ou lucro é produzido.

Regras:
- inventário: exclusivamente ``finalized_buy.ledger`` (líquido confirmado); nunca saldo
  de carteira, ``GridOwnedInventory`` isolado, outra célula/ciclo ou BTC Core
  (GRID CANNOT SELL CORE BTC);
- preço-alvo: ``cell.sell_level.price`` da célula da compra; sem preço atual, candles ou
  bid/ask;
- quantidade candidata: ``floor`` explícito ao ``step_size`` (nunca ceil/nearest); o
  residual ``net - candidata`` é preservado e é só diferença matemática: nada foi vendido;
- regras de mercado verificadas com ``MarketRules.check``; máximos/mínimos violados
  bloqueiam a proposta, sem reduzir, aumentar ou dividir a quantidade.

O assessment guarda só as FONTES (compra finalizada, estado, regras); todos os números são
derivados delas, então não há como construir um assessment com valores contraditórios.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from gridbot.domain.assets import Symbol
from gridbot.domain.errors import DomainError, FloatNotAllowedError
from gridbot.domain.rules import MarketRules, RuleViolation
from gridbot.domain.values import Money, Price, Qty
from gridbot.portfolio.buy_finalization import FinalizedBuy
from gridbot.strategy.grid_state import CellCycleRef, GridCell, GridState


class SellSizingStatus(StrEnum):
    NO_INVENTORY = "NO_INVENTORY"
    """Compra finalizada sem nenhum fill: inventário zero."""
    BELOW_STEP = "BELOW_STEP"
    """Inventário positivo, mas menor que um step: candidata zero."""
    MARKET_RULES_BLOCKED = "MARKET_RULES_BLOCKED"
    """Candidata positiva, mas alguma regra de mercado reprova a proposta."""
    ELIGIBLE_FOR_SELL_SIZING = "ELIGIBLE_FOR_SELL_SIZING"
    """Candidata positiva e todas as regras satisfeitas. NÃO é ordem autorizada."""


class SellSizingErrorCode(StrEnum):
    SYMBOL_MISMATCH = "SYMBOL_MISMATCH"
    UNKNOWN_CELL = "UNKNOWN_CELL"
    CYCLE_MISMATCH = "CYCLE_MISMATCH"
    BUY_PRICE_MISMATCH = "BUY_PRICE_MISMATCH"
    INVALID_ASSESSMENT = "INVALID_ASSESSMENT"


class SellSizingError(DomainError):
    """Vínculo inválido entre compra finalizada, estado e regras; ``code`` diz o motivo."""

    def __init__(self, code: SellSizingErrorCode, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


_E = SellSizingErrorCode


def _expect(value: object, expected: type, field: str) -> None:
    if isinstance(value, float):
        raise FloatNotAllowedError(field)
    if not isinstance(value, expected):
        raise TypeError(f"{field}: esperado {expected.__name__}, recebido {type(value).__name__}")


def _bound_cell(finalized: FinalizedBuy, state: GridState, rules: MarketRules) -> GridCell:
    """Valida o vínculo e devolve a célula da compra. Levanta no primeiro problema."""
    _expect(finalized, FinalizedBuy, "finalized_buy")
    _expect(state, GridState, "grid_state")
    _expect(rules, MarketRules, "market_rules")
    symbol = finalized.symbol
    if state.plan.spec.symbol != symbol or rules.symbol != symbol:
        raise SellSizingError(
            _E.SYMBOL_MISMATCH,
            f"compra de {symbol}, grid de {state.plan.spec.symbol}, regras de {rules.symbol}",
        )
    ref = finalized.cycle_ref
    if ref.cell_index >= len(state.cells):
        raise SellSizingError(_E.UNKNOWN_CELL, f"célula {ref.cell_index} não existe no estado")
    cell_state = state.cells[ref.cell_index]
    if cell_state.cycle_seq != ref.cycle_seq:
        raise SellSizingError(
            _E.CYCLE_MISMATCH,
            f"compra de {ref}; célula está no ciclo {cell_state.cycle_seq}",
        )
    if cell_state.cell.buy_price != finalized.ledger.intent.price:
        raise SellSizingError(
            _E.BUY_PRICE_MISMATCH,
            f"limite {finalized.ledger.intent.price} != buy da célula {cell_state.cell.buy_price}",
        )
    return cell_state.cell


@dataclass(frozen=True, slots=True)
class SellSizingAssessment:
    """Avaliação de uma possível venda do inventário de UMA compra finalizada.

    Campos = fontes revalidadas na construção (direta ou via ``assess_sell_sizing``); um
    vínculo inválido levanta ``INVALID_ASSESSMENT``. Todo o resto é derivado:
    ``candidate + residual == net``, ``0 <= residual < step``, ``candidate`` múltiplo do
    step, e ``eligible_sell_qty`` só existe no status elegível.
    """

    finalized_buy: FinalizedBuy
    grid_state: GridState
    market_rules: MarketRules

    def __post_init__(self) -> None:
        try:
            _bound_cell(self.finalized_buy, self.grid_state, self.market_rules)
        except (SellSizingError, TypeError) as exc:
            raise SellSizingError(_E.INVALID_ASSESSMENT, f"construção inválida: {exc}") from exc

    # ---------------------------------------------------------------- identidade

    @property
    def symbol(self) -> Symbol:
        return self.finalized_buy.symbol

    @property
    def cycle_ref(self) -> CellCycleRef:
        return self.finalized_buy.cycle_ref

    @property
    def cell(self) -> GridCell:
        return self.grid_state.cells[self.cycle_ref.cell_index].cell

    # ---------------------------------------------------------------- números derivados

    @property
    def target_sell_price(self) -> Price:
        return self.cell.sell_price

    @property
    def confirmed_net_qty(self) -> Qty:
        """Líquido confirmado da compra finalizada (do ledger; exato)."""
        return self.finalized_buy.net_acquired_base_qty

    @property
    def step_size(self) -> Qty:
        return self.market_rules.quantity.step_size

    @property
    def quantized_candidate_qty(self) -> Qty:
        """``floor(confirmed_net_qty, step_size)``: nunca maior que o líquido."""
        return self.market_rules.quantity.floor(self.confirmed_net_qty)

    @property
    def step_residual_qty(self) -> Qty:
        """Diferença matemática da quantização. NÃO é saldo pós-venda: nada foi vendido."""
        return self.confirmed_net_qty - self.quantized_candidate_qty

    @property
    def candidate_notional(self) -> Money:
        """``target_sell_price * candidata`` em quote. Não é receita realizada."""
        return self.market_rules.notional_of(self.target_sell_price, self.quantized_candidate_qty)

    @property
    def market_rule_violations(self) -> tuple[RuleViolation, ...]:
        """Violações da proposta (preço-alvo, candidata); vazio se não há candidata."""
        if self.quantized_candidate_qty.is_zero:
            return ()
        check = self.market_rules.check(
            self.symbol, self.target_sell_price, self.quantized_candidate_qty
        )
        return check.violations

    @property
    def eligibility_status(self) -> SellSizingStatus:
        if self.confirmed_net_qty.is_zero:
            return SellSizingStatus.NO_INVENTORY
        if self.quantized_candidate_qty.is_zero:
            return SellSizingStatus.BELOW_STEP
        if self.market_rule_violations:
            return SellSizingStatus.MARKET_RULES_BLOCKED
        return SellSizingStatus.ELIGIBLE_FOR_SELL_SIZING

    @property
    def eligible_sell_qty(self) -> Qty | None:
        """Candidata, só no status elegível; ``None`` caso contrário. Não autoriza ordem."""
        if self.eligibility_status is SellSizingStatus.ELIGIBLE_FOR_SELL_SIZING:
            return self.quantized_candidate_qty
        return None


def assess_sell_sizing(
    finalized_buy: FinalizedBuy, grid_state: GridState, market_rules: MarketRules
) -> SellSizingAssessment:
    """Avalia a venda do inventário de uma compra finalizada, sem efeitos colaterais.

    Recusa (com o código específico) símbolo divergente, célula inexistente, célula em
    outro ciclo ou buy da célula diferente do limite da compra. Não transita o
    ``GridState`` (não exige WAITING_SELL), não debita inventário e não cria ordens.
    """
    _bound_cell(finalized_buy, grid_state, market_rules)
    return SellSizingAssessment(finalized_buy, grid_state, market_rules)
