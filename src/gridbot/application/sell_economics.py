"""A18: economic projections and proposed effects; no operational settlement."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from gridbot.application.operational_grid import GridOperationalBook
from gridbot.application.sell_evidence import _guard, _typed
from gridbot.application.sell_fills import SellFillLedger
from gridbot.application.sell_order_binding import ExternalSellOrderBinding
from gridbot.application.sell_terminal import (
    SellJournalReference,
    SellStructuralState,
    SellTerminalOutcome,
    SellTerminalReconciliation,
    validate_terminal_reconciliation_against_current,
)
from gridbot.domain.assets import Symbol
from gridbot.domain.errors import DomainError
from gridbot.domain.values import Money, Qty
from gridbot.portfolio.buy_finalization import FinalizedBuy


class SellEconomicBlocker(StrEnum):
    EVIDENCE_NOT_RECONCILED = "EVIDENCE_NOT_RECONCILED"
    TERMINAL_SOURCE_REFERENCE_MISSING = "TERMINAL_SOURCE_REFERENCE_MISSING"
    EXTERNAL_PROVENANCE_UNVERIFIED = "EXTERNAL_PROVENANCE_UNVERIFIED"
    OPERATIONAL_SETTLEMENT_NOT_AUTHORIZED = "OPERATIONAL_SETTLEMENT_NOT_AUTHORIZED"
    CAPITAL_CONTRACT_NOT_APPROVED = "CAPITAL_CONTRACT_NOT_APPROVED"
    COST_ALLOCATION_NOT_APPROVED = "COST_ALLOCATION_NOT_APPROVED"
    THIRD_ASSET_COST_UNVALUED = "THIRD_ASSET_COST_UNVALUED"
    THIRD_ASSET_FUNDING_UNVERIFIED = "THIRD_ASSET_FUNDING_UNVERIFIED"
    CYCLE_POLICY_NOT_APPROVED = "CYCLE_POLICY_NOT_APPROVED"


class SellConsumptionDecision(StrEnum):
    """Comparison of supplied claims only, never evidence of an applied credit."""

    SETTLEMENT_IDENTITY = "SETTLEMENT_IDENTITY"
    SETTLEMENT_ALREADY_APPLIED = "SETTLEMENT_ALREADY_APPLIED"
    SETTLEMENT_CONFLICT = "SETTLEMENT_CONFLICT"
    STALE_FINANCIAL_ROOT = "STALE_FINANCIAL_ROOT"
    PENDING_EVIDENCE = "PENDING_EVIDENCE"


@dataclass(frozen=True, slots=True)
class SellEconomicAssessment:
    """Canonical supplied reconciliation; incomplete evidence has no projection.

    All outcomes remain externally unverified. No numerical caches or applied effects.
    Findings/raw remain accessible through reconciliation, even when projection is None.
    """

    reconciliation: SellTerminalReconciliation

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        with _guard():
            _typed(self.reconciliation, SellTerminalReconciliation)
            replace(self.reconciliation)

    @property
    def projection(self) -> SellEconomicProjection | None:
        self._validate()
        if self.reconciliation.state is not SellStructuralState.STRUCTURALLY_RECONCILED:
            return None
        return SellEconomicProjection(self.reconciliation)

    @property
    def settlement_blockers(self) -> tuple[SellEconomicBlocker, ...]:
        self._validate()
        blockers = [
            SellEconomicBlocker.EXTERNAL_PROVENANCE_UNVERIFIED,
            SellEconomicBlocker.OPERATIONAL_SETTLEMENT_NOT_AUTHORIZED,
            SellEconomicBlocker.CAPITAL_CONTRACT_NOT_APPROVED,
            SellEconomicBlocker.CYCLE_POLICY_NOT_APPROVED,
        ]
        projection = self.projection
        if projection is None:
            blockers.append(SellEconomicBlocker.EVIDENCE_NOT_RECONCILED)
        elif projection.outcome is not SellTerminalOutcome.NO_EXECUTION:
            blockers.append(SellEconomicBlocker.COST_ALLOCATION_NOT_APPROVED)
            if projection.unvalued_third_asset_fees:
                blockers.extend(
                    (
                        SellEconomicBlocker.THIRD_ASSET_COST_UNVALUED,
                        SellEconomicBlocker.THIRD_ASSET_FUNDING_UNVERIFIED,
                    )
                )
        if projection is not None and projection.terminal_source_ref is None:
            blockers.append(SellEconomicBlocker.TERMINAL_SOURCE_REFERENCE_MISSING)
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class SellEconomicProjection:
    """Projected lot effects. NO_EXECUTION is a cancellation assessment, not a sale.

    N is the net GRID BUY origin. The existing A13 contract allows exactly one
    commitment per origin/cycle. No claim about wallet balances or other external orders.
    Each access revalidates nested sources, including direct/hostile frozen tampering.
    """

    reconciliation: SellTerminalReconciliation

    def __post_init__(self) -> None:
        with _guard():
            ledger = self._ledger()
            # Validate all new arithmetic before exposing a projection.
            n = ledger.context.intent.finalized_buy.net_acquired_base_qty
            q = ledger.context.requested_qty
            h = ledger.context.intent.base_fee_hold
            x = ledger.gross_executed_qty
            b = ledger.base_fee_qty
            consumed = x + b
            remainder = (q - x) + (h - b)
            remaining = n - consumed
            unreserved = n - (q + h)
            if consumed > q + h or unreserved + remainder != remaining:
                raise DomainError("BTC conservation failed")

    def _ledger(self) -> SellFillLedger:
        with _guard():
            _typed(self.reconciliation, SellTerminalReconciliation)
            replace(self.reconciliation)
            if self.reconciliation.state is not SellStructuralState.STRUCTURALLY_RECONCILED:
                raise DomainError("economic projection requires reconciled terminal sources")
            ledger = self.reconciliation.ledger
            if ledger is None:
                raise DomainError("economic projection requires a ledger")
            return ledger

    @property
    def binding(self) -> ExternalSellOrderBinding:
        self._ledger()
        binding = self.reconciliation.book.external_binding_for(self.reconciliation.cycle_ref)
        if binding is None:
            raise DomainError("economic identity requires external binding")
        return binding

    @property
    def settlement_identity(self) -> tuple[str, str, str, Symbol, str]:
        """External order namespace; witness revision/capture cannot create a new credit."""
        return self.binding.external_order_key

    @property
    def terminal_source_ref(self) -> str | None:
        self._ledger()
        report = self.reconciliation.report
        if report is None:
            raise DomainError("terminal report absent")
        return report.source_ref

    @property
    def outcome(self) -> SellTerminalOutcome:
        self._ledger()
        outcome = self.reconciliation.outcome
        if outcome is None:
            raise DomainError("terminal outcome absent")
        return outcome

    @property
    def origin_buy(self) -> FinalizedBuy:
        return self._ledger().context.intent.finalized_buy

    @property
    def origin_net_base_qty(self) -> Qty:
        return self.origin_buy.net_acquired_base_qty

    @property
    def authorized_sell_qty(self) -> Qty:
        return self._ledger().context.requested_qty

    @property
    def base_fee_hold(self) -> Qty:
        return self._ledger().context.intent.base_fee_hold

    @property
    def executed_qty(self) -> Qty:
        return self._ledger().gross_executed_qty

    @property
    def base_fee_qty(self) -> Qty:
        return self._ledger().base_fee_qty

    @property
    def projected_base_consumption(self) -> Qty:
        ledger = self._ledger()
        return ledger.gross_executed_qty + ledger.base_fee_qty

    @property
    def unexecuted_qty(self) -> Qty:
        return self._ledger().remaining_qty

    @property
    def projected_fee_hold_remainder(self) -> Qty:
        ledger = self._ledger()
        return ledger.context.intent.base_fee_hold - ledger.base_fee_qty

    @property
    def projected_reserved_remainder(self) -> Qty:
        ledger = self._ledger()
        return ledger.remaining_qty + (ledger.context.intent.base_fee_hold - ledger.base_fee_qty)

    @property
    def projected_origin_remaining(self) -> Qty:
        ledger = self._ledger()
        return ledger.context.intent.finalized_buy.net_acquired_base_qty - (
            ledger.gross_executed_qty + ledger.base_fee_qty
        )

    @property
    def unreserved_before(self) -> Qty:
        ledger = self._ledger()
        return ledger.context.intent.finalized_buy.net_acquired_base_qty - (
            ledger.context.requested_qty + ledger.context.intent.base_fee_hold
        )

    @property
    def gross_observed_quote(self) -> Money:
        return self._ledger().gross_observed_quote

    @property
    def quote_fee(self) -> Money:
        return self._ledger().quote_fee

    @property
    def net_observed_quote(self) -> Money:
        ledger = self._ledger()
        return ledger.gross_observed_quote - ledger.quote_fee

    @property
    def fees_by_asset(self) -> tuple[Money, ...]:
        return self._ledger().fees_by_asset

    @property
    def third_asset_fees(self) -> tuple[Money, ...]:
        return self._ledger().third_asset_fees

    @property
    def unvalued_third_asset_fees(self) -> tuple[Money, ...]:
        """BUY and SELL observations separately conserved, never summed across assets."""
        ledger = self._ledger()
        return (
            *ledger.context.intent.finalized_buy.ledger.unvalued_fees,
            *(fee for fee in ledger.third_asset_fees if fee.amount > 0),
        )

    @property
    def identified_origin_quote_debit(self) -> Money:
        """Entire BUY notional from observed prices/qty + quote fees; NOT allocated cost.

        A8 BUY has no independent observed quote field. This is structurally derived
        acquisition debit, not an exchange-authenticated cost or tax cost basis.
        """
        return self.origin_buy.quote_debit_total

    @property
    def allocated_cost(self) -> None:
        self._ledger()
        return None

    @property
    def realized_pnl(self) -> None:
        self._ledger()
        return None


def _same_economic_event(left: SellEconomicProjection, right: SellEconomicProjection) -> bool:
    """Compare economic content, excluding capture/revision and unrelated root history."""
    a, b = left._ledger(), right._ledger()
    return (
        left.binding == right.binding
        and a.context.execution_ref == b.context.execution_ref
        and a.context.intent.reservation == b.context.intent.reservation
        and a.fills == b.fills
        and left.outcome == right.outcome
        and left.reconciliation.observed_status == right.reconciliation.observed_status
    )


@dataclass(frozen=True, slots=True)
class SellEconomicSettlementPlan:
    """Pure proposed effects and claim comparison, with all execution gates closed.

    prior_claims are supplied assessments, NOT an authoritative applied-event registry.
    ALREADY_APPLIED only means a matching supplied prior claim. Empty claims do not
    prove absence of a persisted settlement. A future transaction must read that registry.
    """

    assessment: SellEconomicAssessment
    current_book: GridOperationalBook
    current_reference: SellJournalReference | None = None
    prior_claims: tuple[SellEconomicAssessment, ...] = ()

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        with _guard():
            _typed(self.assessment, SellEconomicAssessment)
            replace(self.assessment)
            _typed(self.current_book, GridOperationalBook)
            replace(self.current_book)
            if self.current_reference is not None:
                _typed(self.current_reference, SellJournalReference)
                replace(self.current_reference)
            _typed(self.prior_claims, tuple)
            for claim in self.prior_claims:
                _typed(claim, SellEconomicAssessment)
                replace(claim)

    @property
    def consumption_decision(self) -> SellConsumptionDecision:
        self._validate()
        source = self.assessment.reconciliation
        projection = self.assessment.projection
        if projection is None:
            return SellConsumptionDecision.PENDING_EVIDENCE
        try:
            validate_terminal_reconciliation_against_current(
                source, self.current_book, self.current_reference
            )
        except DomainError:
            return SellConsumptionDecision.STALE_FINANCIAL_ROOT
        matched = False
        for claim in self.prior_claims:
            previous = claim.projection
            if previous is None:
                # An unresolved supplied prior claim cannot establish non-consumption.
                return SellConsumptionDecision.PENDING_EVIDENCE
            same_namespace = previous.settlement_identity[:4] == projection.settlement_identity[:4]
            overlap = previous.settlement_identity == projection.settlement_identity or (
                same_namespace
                and (
                    previous.binding.cycle_ref == projection.binding.cycle_ref
                    or previous.binding.identity.execution_ref
                    == projection.binding.identity.execution_ref
                )
            )
            if overlap:
                if not _same_economic_event(previous, projection):
                    return SellConsumptionDecision.SETTLEMENT_CONFLICT
                matched = True
        return (
            SellConsumptionDecision.SETTLEMENT_ALREADY_APPLIED
            if matched
            else SellConsumptionDecision.SETTLEMENT_IDENTITY
        )

    @property
    def potential_effects(self) -> SellEconomicProjection | None:
        """Withheld on stale/conflicting/repeated claims; no effects applied in any case."""
        if self.consumption_decision is not SellConsumptionDecision.SETTLEMENT_IDENTITY:
            return None
        return self.assessment.projection

    @property
    def eligible_quote_credit(self) -> None:
        self._validate()
        return None

    @property
    def operational_credit(self) -> None:
        self._validate()
        return None

    @property
    def effects_applied(self) -> bool:
        self._validate()
        return False

    @property
    def settlement_blockers(self) -> tuple[SellEconomicBlocker, ...]:
        self._validate()
        return self.assessment.settlement_blockers
