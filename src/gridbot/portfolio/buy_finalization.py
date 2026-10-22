"""Finalização e reconciliação puras de execuções BUY (ADR-017).

OBSERVED_FILL != FINALIZED_EXECUTION.

``GridBuyIntent`` -> ``BuyFillLedger`` -> relatório terminal externo -> evidência de
reconciliação -> ``finalize_buy`` -> ``FinalizedBuy``.

Uma compra só é finalizada quando três fontes independentes concordam: o ledger local, o
relatório terminal e a evidência de completude dos trades (mesma execução, símbolo e
ciclo; status terminal; quantidade acumulada igual ao bruto do ledger; e exatamente o
mesmo conjunto de ``fill_ref``). Nada é ajustado, completado ou gerado.

Limite de confiança: o núcleo verifica CONSISTÊNCIA entre as evidências recebidas, mas não
consegue provar que a fonte externa é autêntica nem que consultou todos os trades. Essa
garantia é da futura camada de execução/adapter e da orquestração.

Fora do escopo (de propósito): ordens, SELL, retry automático, alteração de ``GridState``,
persistência e deduplicação global (GLOBAL_PERSISTENT_FILL_DEDUPLICATION continua pendente).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from gridbot.domain.assets import Symbol
from gridbot.domain.errors import DomainError, FloatNotAllowedError
from gridbot.domain.values import Money, Qty
from gridbot.portfolio.buy_fills import BuyFillLedger, GridOwnedInventory, is_valid_external_ref
from gridbot.strategy.buy_intents import GridBuyIntent
from gridbot.strategy.grid_state import CellCycleRef


class BuyExecutionStatus(StrEnum):
    """Estado observado da ordem BUY, em termos do domínio (não da exchange).

    Estados específicos de provedor (ex.: ``EXPIRED_IN_MATCH`` da Binance) serão convertidos
    no adapter.
    """

    OPEN = "OPEN"
    PARTIALLY_FILLED_OPEN = "PARTIALLY_FILLED_OPEN"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"

    @property
    def is_terminal(self) -> bool:
        return self not in (BuyExecutionStatus.OPEN, BuyExecutionStatus.PARTIALLY_FILLED_OPEN)


class AcquisitionOutcome(StrEnum):
    """Resultado econômico da compra finalizada, independente do status externo."""

    NO_FILL = "NO_FILL"
    FULLY_ACQUIRED = "FULLY_ACQUIRED"
    PARTIALLY_ACQUIRED = "PARTIALLY_ACQUIRED"


class BuyFinalizationErrorCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    INTENT_MISMATCH = "INTENT_MISMATCH"
    EXECUTION_REF_MISMATCH = "EXECUTION_REF_MISMATCH"
    SYMBOL_MISMATCH = "SYMBOL_MISMATCH"
    CYCLE_MISMATCH = "CYCLE_MISMATCH"
    NOT_TERMINAL = "NOT_TERMINAL"
    RECONCILIATION_MISMATCH = "RECONCILIATION_MISMATCH"
    MISSING_FILL = "MISSING_FILL"
    """A fonte externa cita um fill que o ledger local ainda não registrou."""
    EXTRA_FILL = "EXTRA_FILL"
    """O ledger local tem um fill que a fonte externa não confirma."""
    DUPLICATE_FILL_REF = "DUPLICATE_FILL_REF"
    INVALID_TERMINAL_STATUS = "INVALID_TERMINAL_STATUS"
    INVALID_FINALIZED_BUY = "INVALID_FINALIZED_BUY"


class BuyFinalizationError(DomainError):
    """Finalização recusada; ``code`` identifica o motivo."""

    def __init__(self, code: BuyFinalizationErrorCode, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


_E = BuyFinalizationErrorCode


def _expect(value: object, expected: type, field: str) -> None:
    if isinstance(value, float):
        raise FloatNotAllowedError(field)
    if not isinstance(value, expected):
        raise TypeError(f"{field}: esperado {expected.__name__}, recebido {type(value).__name__}")


def _check_refs(refs: object, field: str) -> None:
    if not isinstance(refs, tuple):
        raise TypeError(f"{field} deve ser tuple[str, ...] (imutável)")
    invalid = [r for r in refs if not is_valid_external_ref(r)]
    if invalid:
        raise BuyFinalizationError(_E.INVALID_INPUT, f"{field} inválidos: {invalid!r}")
    if len(set(refs)) != len(refs):
        raise BuyFinalizationError(_E.DUPLICATE_FILL_REF, f"{field} com referências repetidas")


# ------------------------------------------------------------------ identidade da execução


@dataclass(frozen=True, slots=True)
class BuyExecutionRef:
    """Identidade opaca da execução (ordem) BUY, fornecida de fora; estável por execução.

    Nunca gerada pela estratégia (sem UUID, random ou relógio). O vínculo confiável com a
    ordem do provedor depende da futura camada de execução.
    """

    value: str

    def __post_init__(self) -> None:
        if not is_valid_external_ref(self.value):
            raise BuyFinalizationError(_E.INVALID_INPUT, f"execution_ref inválido: {self.value!r}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class BuyExecutionContext:
    """Vínculo entre a intenção BUY e a execução externa que a representa."""

    intent: GridBuyIntent
    execution_ref: BuyExecutionRef

    def __post_init__(self) -> None:
        _expect(self.intent, GridBuyIntent, "intent")
        _expect(self.execution_ref, BuyExecutionRef, "execution_ref")

    @property
    def symbol(self) -> Symbol:
        return self.intent.symbol

    @property
    def cycle_ref(self) -> CellCycleRef:
        return self.intent.cycle_ref


# ------------------------------------------------------------------ evidências externas


@dataclass(frozen=True, slots=True)
class ObservedBuyTerminalReport:
    """Estado final da execução, informado por uma futura camada de execução.

    Pode carregar qualquer status; ``finalize_buy`` exige que seja terminal.
    """

    execution_ref: BuyExecutionRef
    symbol: Symbol
    cycle_ref: CellCycleRef
    final_status: BuyExecutionStatus
    cumulative_executed_qty: Qty
    fill_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _expect(self.execution_ref, BuyExecutionRef, "execution_ref")
        _expect(self.symbol, Symbol, "symbol")
        _expect(self.cycle_ref, CellCycleRef, "cycle_ref")
        _expect(self.final_status, BuyExecutionStatus, "final_status")
        _expect(self.cumulative_executed_qty, Qty, "cumulative_executed_qty")
        _check_refs(self.fill_refs, "fill_refs")


@dataclass(frozen=True, slots=True)
class BuyFillReconciliationEvidence:
    """Visão externa completa dos trades vinculados à execução terminal.

    ``fill_refs`` é o CONJUNTO completo conhecido pela fonte externa (a ordem não importa;
    repetição é erro). Consistência é verificável aqui; autenticidade e completude da fonte
    não são.
    """

    execution_ref: BuyExecutionRef
    symbol: Symbol
    cycle_ref: CellCycleRef
    cumulative_executed_qty: Qty
    fill_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _expect(self.execution_ref, BuyExecutionRef, "execution_ref")
        _expect(self.symbol, Symbol, "symbol")
        _expect(self.cycle_ref, CellCycleRef, "cycle_ref")
        _expect(self.cumulative_executed_qty, Qty, "cumulative_executed_qty")
        _check_refs(self.fill_refs, "fill_refs")


# ------------------------------------------------------------------ verificação


def _compare_refs(source: str, external: tuple[str, ...], ledger_refs: frozenset[str]) -> None:
    external_set = frozenset(external)
    missing = sorted(external_set - ledger_refs)
    if missing:
        raise BuyFinalizationError(
            _E.MISSING_FILL, f"{source} cita fills ausentes do ledger: {missing}"
        )
    extra = sorted(ledger_refs - external_set)
    if extra:
        raise BuyFinalizationError(
            _E.EXTRA_FILL, f"ledger tem fills não confirmados por {source}: {extra}"
        )


def _verify(
    context: BuyExecutionContext,
    ledger: BuyFillLedger,
    report: ObservedBuyTerminalReport,
    evidence: BuyFillReconciliationEvidence,
) -> None:
    """Todas as condições de finalização; levanta no primeiro problema, em ordem fixa."""
    _expect(context, BuyExecutionContext, "context")
    _expect(ledger, BuyFillLedger, "ledger")
    _expect(report, ObservedBuyTerminalReport, "terminal_report")
    _expect(evidence, BuyFillReconciliationEvidence, "reconciliation_evidence")

    if ledger.intent != context.intent:
        raise BuyFinalizationError(_E.INTENT_MISMATCH, "ledger pertence a outra intenção")
    for source, item in (("terminal_report", report), ("evidence", evidence)):
        if item.execution_ref != context.execution_ref:
            raise BuyFinalizationError(
                _E.EXECUTION_REF_MISMATCH,
                f"{source} de {item.execution_ref}, contexto de {context.execution_ref}",
            )
        if item.symbol != context.symbol:
            raise BuyFinalizationError(
                _E.SYMBOL_MISMATCH, f"{source} de {item.symbol}, contexto de {context.symbol}"
            )
        if item.cycle_ref != context.cycle_ref:
            raise BuyFinalizationError(
                _E.CYCLE_MISMATCH, f"{source} de {item.cycle_ref}, contexto de {context.cycle_ref}"
            )

    if not report.final_status.is_terminal:
        raise BuyFinalizationError(_E.NOT_TERMINAL, f"status {report.final_status} não é terminal")

    gross = ledger.gross_filled_qty
    for source, qty in (
        ("terminal_report", report.cumulative_executed_qty),
        ("evidence", evidence.cumulative_executed_qty),
    ):
        if qty != gross:
            raise BuyFinalizationError(
                _E.RECONCILIATION_MISMATCH,
                f"{source} declara {qty} executado; ledger tem {gross}",
            )

    ledger_refs = frozenset(f.fill_ref for f in ledger.fills)
    _compare_refs("evidence", evidence.fill_refs, ledger_refs)
    _compare_refs("terminal_report", report.fill_refs, ledger_refs)

    _check_status_semantics(report.final_status, gross, ledger.intended_qty)


def _check_status_semantics(status: BuyExecutionStatus, gross: Qty, intended: Qty) -> None:
    if status is BuyExecutionStatus.FILLED and gross != intended:
        raise BuyFinalizationError(
            _E.INVALID_TERMINAL_STATUS, f"FILLED exige {intended} executado; houve {gross}"
        )
    if status in (BuyExecutionStatus.CANCELED, BuyExecutionStatus.EXPIRED) and gross >= intended:
        raise BuyFinalizationError(
            _E.INVALID_TERMINAL_STATUS,
            f"{status} exige execução menor que a pretendida ({gross} >= {intended})",
        )
    if status is BuyExecutionStatus.REJECTED and not gross.is_zero:
        raise BuyFinalizationError(
            _E.INVALID_TERMINAL_STATUS,
            f"REJECTED com {gross} executado é inconsistência que exige reconciliação",
        )


# ------------------------------------------------------------------ resultado


@dataclass(frozen=True, slots=True)
class FinalizedBuy:
    """Compra BUY com execução terminal e reconciliada segundo as evidências recebidas.

    Toda quantidade e todo inventário são derivados do ledger (nunca recebidos prontos).
    A construção revalida todas as condições de ``finalize_buy``; uma construção direta
    adulterada levanta ``INVALID_FINALIZED_BUY``. Não altera ``GridState`` e não autoriza
    venda: ``is_sell_sizing_candidate`` != ordem SELL permitida.
    """

    context: BuyExecutionContext
    ledger: BuyFillLedger
    terminal_report: ObservedBuyTerminalReport
    reconciliation_evidence: BuyFillReconciliationEvidence

    def __post_init__(self) -> None:
        try:
            _verify(self.context, self.ledger, self.terminal_report, self.reconciliation_evidence)
        except (BuyFinalizationError, TypeError) as exc:
            raise BuyFinalizationError(
                _E.INVALID_FINALIZED_BUY, f"construção inválida: {exc}"
            ) from exc

    @property
    def execution_ref(self) -> BuyExecutionRef:
        return self.context.execution_ref

    @property
    def symbol(self) -> Symbol:
        return self.context.symbol

    @property
    def cycle_ref(self) -> CellCycleRef:
        return self.context.cycle_ref

    @property
    def final_status(self) -> BuyExecutionStatus:
        return self.terminal_report.final_status

    @property
    def outcome(self) -> AcquisitionOutcome:
        gross = self.ledger.gross_filled_qty
        if gross.is_zero:
            return AcquisitionOutcome.NO_FILL
        if gross == self.ledger.intended_qty:
            return AcquisitionOutcome.FULLY_ACQUIRED
        return AcquisitionOutcome.PARTIALLY_ACQUIRED

    @property
    def gross_filled_qty(self) -> Qty:
        return self.ledger.gross_filled_qty

    @property
    def unexecuted_qty(self) -> Qty:
        """Parte da intenção original que não foi executada (e não será, sem retry)."""
        return self.ledger.remaining_qty

    @property
    def net_acquired_base_qty(self) -> Qty:
        """Inventário líquido exato do ledger; nunca quantizado (dust preservado)."""
        return self.ledger.net_acquired_base_qty

    @property
    def fees_by_asset(self) -> tuple[Money, ...]:
        return self.ledger.fees_by_asset

    @property
    def quote_debit_total(self) -> Money:
        return self.ledger.quote_debit_total

    @property
    def has_unvalued_fees(self) -> bool:
        return self.ledger.has_unvalued_fees

    @property
    def inventory(self) -> GridOwnedInventory:
        """Projeção do inventário derivada do ledger desta finalização."""
        return self.ledger.grid_owned_inventory

    @property
    def is_sell_sizing_candidate(self) -> bool:
        """Terminal + reconciliada + inventário líquido > 0. NÃO autoriza ordem SELL."""
        return not self.net_acquired_base_qty.is_zero


def finalize_buy(
    execution_context: BuyExecutionContext,
    ledger: BuyFillLedger,
    terminal_report: ObservedBuyTerminalReport,
    reconciliation_evidence: BuyFillReconciliationEvidence,
) -> FinalizedBuy:
    """Finaliza uma compra se, e só se, ledger, relatório terminal e evidência concordam.

    Falha (sem alterar nada) com o código do primeiro problema encontrado. Não completa
    fills, não ajusta quantidades, não gera ordens, não faz retry e não altera ``GridState``.
    """
    _verify(execution_context, ledger, terminal_report, reconciliation_evidence)
    return FinalizedBuy(execution_context, ledger, terminal_report, reconciliation_evidence)
