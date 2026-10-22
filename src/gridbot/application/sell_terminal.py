"""A17.5: fechamento estrutural fornecido, separado de procedência e consumo."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from gridbot.application.operational_grid import GridOperationalBook
from gridbot.application.operational_persistence import OperationalScope, require_revision
from gridbot.application.sell_evidence import (
    ObservedSellOrderReport,
    SellTradeCollection,
    _guard,
    _nested,
    _typed,
)
from gridbot.application.sell_fills import SellFillLedger
from gridbot.application.sell_lifecycle import SellAttemptStatus
from gridbot.application.sell_order_binding import ExternalSellOrderBinding
from gridbot.application.sell_reconciliation import (
    SellFindingKind,
    SellReconciliationAssessment,
    SellReconciliationCode,
    SellReconciliationFinding,
    _evaluate,
)
from gridbot.domain.enums import OrderStatus
from gridbot.domain.errors import DomainError
from gridbot.domain.values import Money, Qty
from gridbot.strategy.grid_state import CellCycleRef


class SellStructuralState(StrEnum):
    PENDING_EVIDENCE = "PENDING_EVIDENCE"
    CONTRADICTORY_EVIDENCE = "CONTRADICTORY_EVIDENCE"
    STRUCTURALLY_RECONCILED = "STRUCTURALLY_RECONCILED"


class SellTerminalOutcome(StrEnum):
    FULL_EXECUTION = "FULL_EXECUTION"
    PARTIAL_EXECUTION = "PARTIAL_EXECUTION"
    NO_EXECUTION = "NO_EXECUTION"


class SellProvenanceLimit(StrEnum):
    PROVIDED_EVIDENCE_EXTERNALLY_UNVERIFIED = "PROVIDED_EVIDENCE_EXTERNALLY_UNVERIFIED"


@dataclass(frozen=True, slots=True)
class SellJournalReference:
    """Localiza fontes; revisão/seq não autenticam a exchange ou o chamador."""

    scope: OperationalScope
    revision: int
    receipt_sequences: tuple[int, ...]

    def __post_init__(self) -> None:
        with _guard():
            _typed(self.scope, OperationalScope)
            replace(self.scope)
            require_revision(self.revision)
            _typed(self.receipt_sequences, tuple)
            for sequence in self.receipt_sequences:
                require_revision(sequence)
                if sequence == 0:
                    raise DomainError("recibo deve ter sequência positiva")
            if self.receipt_sequences != tuple(sorted(set(self.receipt_sequences))):
                raise DomainError("recibos devem ser únicos e canônicos")


C = SellReconciliationCode
K = SellFindingKind
_PROVENANCE_FINDINGS = frozenset(
    {C.EXTERNAL_IDENTITY_UNAUTHENTICATED, C.EXTERNAL_COMPLETENESS_UNCONFIRMED}
)
_PARTIAL_STATUSES = frozenset(
    {OrderStatus.CANCELED, OrderStatus.EXPIRED, OrderStatus.EXPIRED_IN_MATCH}
)


@dataclass(frozen=True, slots=True)
class SellTerminalReconciliation:
    """Fontes imutáveis; estado/outcome/totais são derivados sem autoridade econômica.

    source_findings conserva impedimentos da seleção raw/replay. Construção direta
    conclui apenas sobre fontes fornecidas; nunca prova ausência de fontes omitidas.
    journal_reference é metadata local, não uma capability de consumo.
    """

    book: GridOperationalBook
    cycle_ref: CellCycleRef
    ledger: SellFillLedger | None
    report: ObservedSellOrderReport | None
    collection: SellTradeCollection | None
    source_findings: tuple[SellReconciliationFinding, ...] = ()
    journal_reference: SellJournalReference | None = None

    def __post_init__(self) -> None:
        _ = self._analysis()

    def _analysis(
        self,
    ) -> tuple[
        SellStructuralState, SellTerminalOutcome | None, tuple[SellReconciliationFinding, ...]
    ]:
        with _guard():
            _typed(self.book, GridOperationalBook)
            replace(self.book)
            _nested(self.cycle_ref, CellCycleRef)
            _typed(self.source_findings, tuple)
            for finding in self.source_findings:
                _typed(finding, SellReconciliationFinding)
                replace(finding)
            if self.report is not None:
                _nested(self.report, ObservedSellOrderReport)
            if self.collection is not None:
                _nested(self.collection, SellTradeCollection)
            if self.journal_reference is not None:
                _typed(self.journal_reference, SellJournalReference)
                replace(self.journal_reference)
                if self.journal_reference.scope.symbol != self.book.grid_state.plan.spec.symbol:
                    raise DomainError("referência de journal usa outro símbolo")
            findings = list(self.source_findings)
            attempt = self.book.attempt_for(self.cycle_ref)
            if self.ledger is None:
                findings.append(
                    SellReconciliationFinding(C.FIELD_MISSING, K.MISSING, "terminal.ledger")
                )
                if attempt is None or attempt.status is not SellAttemptStatus.EXECUTION_BOUND:
                    findings.append(
                        SellReconciliationFinding(
                            C.ORDER_BINDING_UNCONFIRMED, K.UNCONFIRMED, "terminal.attempt"
                        )
                    )
            else:
                _typed(self.ledger, SellFillLedger)
                if self.ledger.context.cycle_ref != self.cycle_ref:
                    findings.append(
                        SellReconciliationFinding(
                            C.CYCLE_MISMATCH,
                            K.CONTRADICTORY,
                            "terminal.cycle",
                            self.cycle_ref,
                            self.ledger.context.cycle_ref,
                        )
                    )
                # Mantém a política A17 histórica intacta para replay/schema 1.
                findings.extend(_evaluate(self.book, self.ledger, self.report, self.collection))
            binding = self.book.external_binding_for(self.cycle_ref)
            if self.journal_reference is not None and binding is not None:
                identity = binding.identity
                scope = self.journal_reference.scope
                if (
                    identity.venue_ref,
                    identity.account_ref,
                    identity.environment_ref,
                    identity.symbol,
                ) != (scope.venue_ref, scope.account_ref, scope.environment_ref, scope.symbol):
                    raise DomainError("referência de journal de outro escopo")
            blockers = tuple(
                f
                for f in findings
                if f.kind is not K.INFORMATION
                and not (f.kind is K.UNCONFIRMED and f.code in _PROVENANCE_FINDINGS)
            )
            if any(f.kind is K.CONTRADICTORY for f in blockers):
                return SellStructuralState.CONTRADICTORY_EVIDENCE, None, tuple(findings)
            if blockers or self.ledger is None or self.report is None:
                return SellStructuralState.PENDING_EVIDENCE, None, tuple(findings)
            qty = self.ledger.gross_executed_qty
            requested = self.ledger.context.requested_qty
            status = self.report.status
            outcome = None
            if status is OrderStatus.FILLED and qty == requested:
                outcome = SellTerminalOutcome.FULL_EXECUTION
            elif status in _PARTIAL_STATUSES and not qty.is_zero and qty < requested:
                outcome = SellTerminalOutcome.PARTIAL_EXECUTION
            elif (status in _PARTIAL_STATUSES or status is OrderStatus.REJECTED) and qty.is_zero:
                outcome = SellTerminalOutcome.NO_EXECUTION
            if outcome is None:
                return SellStructuralState.PENDING_EVIDENCE, None, tuple(findings)
            return SellStructuralState.STRUCTURALLY_RECONCILED, outcome, tuple(findings)

    @property
    def state(self) -> SellStructuralState:
        return self._analysis()[0]

    @property
    def outcome(self) -> SellTerminalOutcome | None:
        return self._analysis()[1]

    @property
    def findings(self) -> tuple[SellReconciliationFinding, ...]:
        return self._analysis()[2]

    @property
    def provenance_limit(self) -> SellProvenanceLimit:
        return SellProvenanceLimit.PROVIDED_EVIDENCE_EXTERNALLY_UNVERIFIED

    @property
    def observed_status(self) -> OrderStatus | None:
        self._analysis()
        return None if self.report is None else self.report.status

    @property
    def assessment(self) -> SellReconciliationAssessment | None:
        self._analysis()
        if self.ledger is None:
            return None
        return SellReconciliationAssessment(self.book, self.ledger, self.report, self.collection)

    @property
    def evidence(self) -> ReconciledSellEvidence | SellNoFillOutcome | None:
        state, outcome, _ = self._analysis()
        if state is not SellStructuralState.STRUCTURALLY_RECONCILED:
            return None
        if outcome is SellTerminalOutcome.NO_EXECUTION:
            return SellNoFillOutcome(self)
        return ReconciledSellEvidence(self)


def _evidence_ledger(
    reconciliation: SellTerminalReconciliation, *, no_fill: bool
) -> SellFillLedger:
    with _guard():
        _typed(reconciliation, SellTerminalReconciliation)
        state, outcome, _ = reconciliation._analysis()
        if state is not SellStructuralState.STRUCTURALLY_RECONCILED:
            raise DomainError("reconciliação estrutural não concluída")
        if (outcome is SellTerminalOutcome.NO_EXECUTION) != no_fill:
            raise DomainError("resultado sem execução difere de venda executada")
        ledger = reconciliation.ledger
        if ledger is None:
            raise DomainError("ledger ausente")
        return ledger


@dataclass(frozen=True, slots=True)
class ReconciledSellEvidence:
    """Somente execução positiva integral/parcial; não autoriza consumir reserva."""

    reconciliation: SellTerminalReconciliation

    def __post_init__(self) -> None:
        _evidence_ledger(self.reconciliation, no_fill=False)

    @property
    def outcome(self) -> SellTerminalOutcome:
        _evidence_ledger(self.reconciliation, no_fill=False)
        outcome = self.reconciliation.outcome
        if outcome is None:
            raise DomainError("outcome ausente")
        return outcome

    @property
    def binding(self) -> ExternalSellOrderBinding:
        _evidence_ledger(self.reconciliation, no_fill=False)
        binding = self.reconciliation.book.external_binding_for(self.reconciliation.cycle_ref)
        if binding is None:
            raise DomainError("binding ausente")
        return binding

    @property
    def executed_qty(self) -> Qty:
        return _evidence_ledger(self.reconciliation, no_fill=False).gross_executed_qty

    @property
    def unexecuted_qty(self) -> Qty:
        return _evidence_ledger(self.reconciliation, no_fill=False).remaining_qty

    @property
    def base_fee_qty(self) -> Qty:
        return _evidence_ledger(self.reconciliation, no_fill=False).base_fee_qty

    @property
    def gross_quote(self) -> Money:
        return _evidence_ledger(self.reconciliation, no_fill=False).gross_observed_quote

    @property
    def quote_fee(self) -> Money:
        return _evidence_ledger(self.reconciliation, no_fill=False).quote_fee

    @property
    def net_observed_quote(self) -> Money:
        return _evidence_ledger(self.reconciliation, no_fill=False).net_observed_quote

    @property
    def third_asset_fees(self) -> tuple[Money, ...]:
        return _evidence_ledger(self.reconciliation, no_fill=False).third_asset_fees

    @property
    def fees_by_asset(self) -> tuple[Money, ...]:
        return _evidence_ledger(self.reconciliation, no_fill=False).fees_by_asset


@dataclass(frozen=True, slots=True)
class SellNoFillOutcome:
    """Ordem encerrada sem execução; não constitui venda ou proceeds zero fictícios."""

    reconciliation: SellTerminalReconciliation

    def __post_init__(self) -> None:
        _evidence_ledger(self.reconciliation, no_fill=True)


def reconcile_sell_terminal(
    book: GridOperationalBook,
    cycle_ref: CellCycleRef,
    ledger: SellFillLedger | None,
    report: ObservedSellOrderReport | None,
    collection: SellTradeCollection | None,
    *,
    source_findings: tuple[SellReconciliationFinding, ...] = (),
    journal_reference: SellJournalReference | None = None,
) -> SellTerminalReconciliation:
    return SellTerminalReconciliation(
        book, cycle_ref, ledger, report, collection, source_findings, journal_reference
    )


def validate_terminal_reconciliation_against_current(
    reconciliation: SellTerminalReconciliation,
    current_book: GridOperationalBook,
    current_reference: SellJournalReference | None = None,
) -> None:
    """Exige fontes/revisão atuais fornecidas; não é operação econômica nem prova externa."""
    with _guard():
        _typed(reconciliation, SellTerminalReconciliation)
        replace(reconciliation)
        if reconciliation.journal_reference != current_reference:
            raise DomainError("referência de journal stale ou não fornecida")
        current = replace(reconciliation, book=current_book)
        if current.state is not SellStructuralState.STRUCTURALLY_RECONCILED:
            raise DomainError("resultado stale/incompleto diante da raiz atual")
