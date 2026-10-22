"""Registros locais derivados; nenhum deles autoriza efeito econômico SELL."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from gridbot.application.operational_persistence import require_revision
from gridbot.application.sell_fills import ObservedSellFill
from gridbot.application.sell_reconciliation import SellReconciliationFinding
from gridbot.exchange.binance.offline_evidence import (
    NormalizedSellObservation,
    OfflineSellIssue,
    RawSellObservation,
)
from gridbot.exchange.binance.offline_replay import OfflineSellProjection, OfflineSellReplayPlan


class ReceiptClassification(StrEnum):
    RECEIVED = "RECEIVED"
    DUPLICATE_IDENTICAL = "DUPLICATE_IDENTICAL"
    DUPLICATE_CONFLICTING = "DUPLICATE_CONFLICTING"
    FOREIGN_SCOPE = "FOREIGN_SCOPE"


@dataclass(frozen=True, slots=True)
class DurableRawReceipt:
    sequence: int
    revision: int
    raw: RawSellObservation
    classification: ReceiptClassification
    duplicate_of: int | None

    def __post_init__(self) -> None:
        require_revision(self.revision)
        require_revision(self.sequence)
        if self.sequence == 0 or type(self.raw) is not RawSellObservation:
            raise TypeError("recibo exige sequência positiva/raw conhecido")
        replace(self.raw)
        if type(self.classification) is not ReceiptClassification:
            raise TypeError("classificação local desconhecida")
        if self.duplicate_of is not None:
            require_revision(self.duplicate_of)
            if not 0 < self.duplicate_of < self.sequence:
                raise TypeError("duplicata exige recibo anterior")
        duplicate = self.classification in {
            ReceiptClassification.DUPLICATE_IDENTICAL,
            ReceiptClassification.DUPLICATE_CONFLICTING,
        }
        if duplicate != (self.duplicate_of is not None):
            raise TypeError("classificação e vínculo de duplicata incompatíveis")


@dataclass(frozen=True, slots=True)
class DurableReplayRecord:
    """Resultado regenerável de fontes registradas, nunca autoridade financeira.

    input_revision/receipt_sequences fixam a visão anterior à gravação deste resultado.
    Reavaliações futuras acrescentam registros; não apagam a quarentena histórica.
    """

    plan: OfflineSellReplayPlan
    input_revision: int
    receipt_sequences: tuple[int, ...]
    normalized: tuple[NormalizedSellObservation, ...]
    issues: tuple[OfflineSellIssue, ...]
    quarantined_sources: tuple[str, ...]
    fills: tuple[ObservedSellFill, ...] | None
    findings: tuple[SellReconciliationFinding, ...] | None

    def __post_init__(self) -> None:
        require_revision(self.input_revision)
        replace(self.plan)
        if type(self.receipt_sequences) is not tuple:
            raise TypeError("sequências exigem tuple")
        for sequence in self.receipt_sequences:
            require_revision(sequence)
            if sequence == 0:
                raise TypeError("sequência de recibo deve ser positiva")
        if self.receipt_sequences != tuple(sorted(set(self.receipt_sequences))):
            raise TypeError("sequências devem ser únicas/canônicas")
        if any(
            type(values) is not tuple
            for values in (self.normalized, self.issues, self.quarantined_sources)
        ):
            raise TypeError("normalização/issues/quarentena exigem tuplas presentes")
        for values, cls in (
            (self.normalized, NormalizedSellObservation),
            (self.issues, OfflineSellIssue),
            (self.quarantined_sources, str),
            (self.fills, ObservedSellFill),
            (self.findings, SellReconciliationFinding),
        ):
            if values is None:
                continue
            if type(values) is not tuple:
                raise TypeError("projeção exige tuplas")
            for value in values:
                if type(value) is not cls:
                    raise TypeError("elemento de projeção inválido")


def replay_record(
    plan: OfflineSellReplayPlan,
    revision: int,
    sequences: tuple[int, ...],
    projection: OfflineSellProjection,
) -> DurableReplayRecord:
    return DurableReplayRecord(
        plan,
        revision,
        sequences,
        projection.normalized,
        projection.issues,
        projection.quarantined_sources,
        None if projection.ledger is None else projection.ledger.fills,
        None if projection.assessment is None else projection.assessment.findings,
    )
