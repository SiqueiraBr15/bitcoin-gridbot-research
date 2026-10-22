"""A17.2: coerência estrutural das fontes fornecidas, nunca autoridade econômica."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from gridbot.application.sell_evidence import _guard, _typed
from gridbot.application.sell_order_binding import ExternalSellOrderBinding
from gridbot.application.sell_reconciliation import (
    SellBindingVerification,
    SellCollectionVerification,
    SellFindingKind,
    SellObservedOutcome,
    SellReconciliationAssessment,
    SellReconciliationCode,
    SellReconciliationFinding,
)
from gridbot.domain.errors import DomainError
from gridbot.domain.values import Money, Qty


class SellCandidateTrustLimit(StrEnum):
    PROVIDED_EVIDENCE_STRUCTURAL_ONLY = "PROVIDED_EVIDENCE_STRUCTURAL_ONLY"


_TRUST_FINDINGS = frozenset(
    (
        SellReconciliationCode.EXTERNAL_IDENTITY_UNAUTHENTICATED,
        SellReconciliationCode.EXTERNAL_COMPLETENESS_UNCONFIRMED,
    )
)


@dataclass(frozen=True, slots=True)
class SellCandidateEligibility:
    assessment: SellReconciliationAssessment

    def __post_init__(self) -> None:
        with _guard():
            _typed(self.assessment, SellReconciliationAssessment)
            replace(self.assessment)

    @property
    def blockers(self) -> tuple[SellReconciliationFinding, ...]:
        return tuple(
            f
            for f in self.assessment.findings
            if f.kind is not SellFindingKind.INFORMATION and f.code not in _TRUST_FINDINGS
        )

    @property
    def is_structurally_eligible(self) -> bool:
        # Os limites de confiança continuam nos diagnósticos residuais.
        return (
            not self.blockers
            and self.assessment.binding_verification is SellBindingVerification.STRUCTURALLY_MATCHED
            and self.assessment.collection_verification
            is SellCollectionVerification.STRUCTURALLY_COHERENT
            and self.assessment.observed_outcome is not SellObservedOutcome.UNDETERMINED
        )


@dataclass(frozen=True, slots=True)
class SellFinalizationCandidate:
    """Armazena fontes; deriva totais/decisão. Não é FinalizedSell nem autorização.

    A construção direta reexecuta critérios. Ingestão deve ainda bloquear qualquer
    observação selecionada recusada/conflitante que não esteja nestes DTOs.
    """

    assessment: SellReconciliationAssessment

    def __post_init__(self) -> None:
        with _guard():
            if not SellCandidateEligibility(self.assessment).is_structurally_eligible:
                raise DomainError("SELL candidato estrutural inelegível; preservar fontes")

    @property
    def trust_limit(self) -> SellCandidateTrustLimit:
        return SellCandidateTrustLimit.PROVIDED_EVIDENCE_STRUCTURAL_ONLY

    @property
    def binding(self) -> ExternalSellOrderBinding:
        # Revalida também uma instância adulterada depois da construção.
        replace(self)
        binding = self.assessment.book.external_binding_for(
            self.assessment.ledger.context.cycle_ref
        )
        if binding is None:
            raise DomainError("binding ausente")
        return binding

    @property
    def executed_qty(self) -> Qty:
        replace(self)
        return self.assessment.ledger.gross_executed_qty

    @property
    def unexecuted_qty(self) -> Qty:
        replace(self)
        return self.assessment.ledger.remaining_qty

    @property
    def gross_quote(self) -> Money:
        replace(self)
        return self.assessment.ledger.gross_observed_quote

    @property
    def net_quote(self) -> Money:
        replace(self)
        return self.assessment.ledger.net_observed_quote

    @property
    def fees_by_asset(self) -> tuple[Money, ...]:
        replace(self)
        return self.assessment.ledger.fees_by_asset

    @property
    def residual_findings(self) -> tuple[SellReconciliationFinding, ...]:
        replace(self)
        return self.assessment.findings
