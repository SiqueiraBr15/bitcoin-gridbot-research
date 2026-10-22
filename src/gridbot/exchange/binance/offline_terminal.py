"""A17.5: fecha somente evidência fornecida; conserva conflitos e eventos tardios."""

from __future__ import annotations

from gridbot.application.sell_evidence import _typed
from gridbot.application.sell_lifecycle import SellAttemptStatus
from gridbot.application.sell_reconciliation import (
    SellFindingKind,
    SellReconciliationCode,
    SellReconciliationFinding,
)
from gridbot.application.sell_terminal import (
    SellJournalReference,
    SellTerminalReconciliation,
    reconcile_sell_terminal,
)
from gridbot.exchange.binance.offline_evidence import (
    NormalizedSellObservation,
    OfflineIssueCode,
    OfflineSellSource,
)
from gridbot.exchange.binance.offline_replay import OfflineSellReplay, _matches

C = SellReconciliationCode
K = SellFindingKind
_CONFLICTS = frozenset(
    {
        OfflineIssueCode.RAW_CONFLICT,
        OfflineIssueCode.TRADE_CONFLICT,
        OfflineIssueCode.IDENTITY_CONFLICT,
        OfflineIssueCode.FINANCIAL_QUARANTINE,
    }
)


def reconcile_offline_sell_terminal(
    replay: OfflineSellReplay,
    *,
    journal_reference: SellJournalReference | None = None,
) -> SellTerminalReconciliation:
    _typed(replay, OfflineSellReplay)
    cycle = replay.plan.query.identity.cycle_ref
    attempt = replay.book.attempt_for(cycle)
    if attempt is None or attempt.status is not SellAttemptStatus.EXECUTION_BOUND:
        return reconcile_sell_terminal(
            replay.book, cycle, None, None, None, journal_reference=journal_reference
        )
    projection = replay.projection
    findings: list[SellReconciliationFinding] = []
    for issue in projection.issues:
        if issue.code is OfflineIssueCode.SOURCE_NOT_SELECTED:
            continue
        findings.append(
            SellReconciliationFinding(
                C.TRADE_FIELD_MISMATCH if issue.code in _CONFLICTS else C.FIELD_MISSING,
                K.CONTRADICTORY if issue.code in _CONFLICTS else K.MISSING,
                "raw:" + issue.source_ref + "." + issue.field,
                observed=issue.detail,
            )
        )
    assessment = projection.assessment
    report = None if assessment is None else assessment.report
    collection = None if assessment is None else assessment.collection
    selected = {
        replay.plan.report_ref,
        replay.plan.before_ref,
        replay.plan.after_ref,
        *replay.plan.page_refs,
        *replay.plan.event_refs,
    }
    # Uma repetição não muda a posição original da fonte nem renova a seleção.
    # Corpos distintos sob a mesma referência já são bloqueados como RAW_CONFLICT.
    positions: dict[str, int] = {}
    for index, raw in enumerate(replay.tape.observations):
        positions.setdefault(raw.source_ref, index)
    last_selected = max(
        (index for source_ref, index in positions.items() if source_ref in selected), default=-1
    )
    current = (
        {}
        if projection.ledger is None
        else {fill.fill_ref: fill for fill in projection.ledger.fills}
    )
    selected_pages = tuple(
        record for record in projection.normalized if record.raw.source_ref in replay.plan.page_refs
    )

    def history(record: NormalizedSellObservation) -> bool:
        """Compara fatos conhecidos; nunca preenche ausência de uma captura com outra."""
        equivalent = not record.issues
        for issue in record.issues:
            if issue.code in {
                OfflineIssueCode.IDENTITY_CONFLICT,
                OfflineIssueCode.MALFORMED,
                OfflineIssueCode.FINANCIAL_PRECISION_ERROR,
            }:
                findings.append(
                    SellReconciliationFinding(
                        C.ORDER_IDENTITY_MISMATCH
                        if issue.code is OfflineIssueCode.IDENTITY_CONFLICT
                        else C.FIELD_MISSING,
                        K.CONTRADICTORY
                        if issue.code is OfflineIssueCode.IDENTITY_CONFLICT
                        else K.MISSING,
                        "history:" + record.raw.source_ref + "." + issue.field,
                        observed=issue.detail,
                    )
                )
        if record.raw.kind is OfflineSellSource.MY_TRADES_PAGE:
            # Igualdade financeira não prova igualdade da paginação, sobretudo
            # para página vazia com continuação. Capture/source IDs podem diferir.
            equivalent = equivalent and any(
                (
                    record.raw.cursor_from,
                    record.raw.next_cursor,
                    record.raw.requested_limit,
                    record.trades,
                )
                == (
                    page.raw.cursor_from,
                    page.raw.next_cursor,
                    page.raw.requested_limit,
                    page.trades,
                )
                for page in selected_pages
            )
        for trade in record.trades:
            if not _matches(trade.identity, replay.plan.query.identity, trade=True):
                findings.append(
                    SellReconciliationFinding(
                        C.ORDER_IDENTITY_MISMATCH,
                        K.CONTRADICTORY,
                        "history:" + record.raw.source_ref + ".trade.identity",
                    )
                )
                equivalent = False
                continue
            fill = current.get(trade.trade_ref)
            if fill is None:
                findings.append(
                    SellReconciliationFinding(
                        C.TRADE_SET_MISMATCH,
                        K.UNCONFIRMED,
                        "history:" + record.raw.source_ref,
                        observed=trade.trade_ref,
                    )
                )
                equivalent = False
                continue
            for name in ("execution_price", "executed_qty", "observed_quote", "fee", "side"):
                old = getattr(trade, name)
                new = getattr(fill, name)
                if old is None:
                    equivalent = False
                elif old != new:
                    equivalent = False
                    findings.append(
                        SellReconciliationFinding(
                            C.TRADE_FIELD_MISMATCH,
                            K.CONTRADICTORY,
                            "history:" + record.raw.source_ref + "." + name,
                            str(new),
                            str(old),
                        )
                    )
            if (
                trade.liquidity is not None
                and fill.liquidity is not None
                and (trade.liquidity != fill.liquidity)
            ):
                equivalent = False
                findings.append(
                    SellReconciliationFinding(
                        C.TRADE_FIELD_MISMATCH,
                        K.CONTRADICTORY,
                        "history:" + record.raw.source_ref + ".liquidity",
                    )
                )
        observed = record.report
        if observed is not None:
            if not _matches(observed.identity, replay.plan.query.identity):
                findings.append(
                    SellReconciliationFinding(
                        C.ORDER_IDENTITY_MISMATCH,
                        K.CONTRADICTORY,
                        "history:" + record.raw.source_ref + ".report.identity",
                    )
                )
                equivalent = False
            elif report is None:
                equivalent = False
            elif observed.status is not None and observed.status.is_terminal:
                for name in (
                    "status",
                    "original_qty",
                    "cumulative_executed_qty",
                    "cumulative_quote",
                    "limit_price",
                    "side",
                    "order_type",
                ):
                    old = getattr(observed, name)
                    new = getattr(report, name)
                    if old is None:
                        equivalent = False
                    elif old != new:
                        equivalent = False
                        findings.append(
                            SellReconciliationFinding(
                                C.COLLECTION_CHANGED,
                                K.CONTRADICTORY,
                                "history:" + record.raw.source_ref + "." + name,
                                str(new),
                                str(old),
                            )
                        )
            else:
                # A ordem pode progredir de aberta a terminal; seus termos não
                # podem mudar silenciosamente e seus cumulativos não retrocedem.
                for name in ("original_qty", "limit_price", "side", "order_type"):
                    old = getattr(observed, name)
                    new = getattr(report, name)
                    if old is not None and old != new:
                        findings.append(
                            SellReconciliationFinding(
                                C.COLLECTION_CHANGED,
                                K.CONTRADICTORY,
                                "history:" + record.raw.source_ref + "." + name,
                                str(new),
                                str(old),
                            )
                        )
                if (
                    observed.cumulative_executed_qty is not None
                    and report.cumulative_executed_qty is not None
                    and observed.cumulative_executed_qty > report.cumulative_executed_qty
                ):
                    findings.append(
                        SellReconciliationFinding(
                            C.EXECUTED_QUANTITY_MISMATCH,
                            K.CONTRADICTORY,
                            "history:" + record.raw.source_ref + ".cumulative_executed_qty",
                            str(report.cumulative_executed_qty),
                            str(observed.cumulative_executed_qty),
                        )
                    )
                if (
                    observed.cumulative_quote is not None
                    and report.cumulative_quote is not None
                    and observed.cumulative_quote.amount > report.cumulative_quote.amount
                ):
                    findings.append(
                        SellReconciliationFinding(
                            C.CUMULATIVE_QUOTE_MISMATCH,
                            K.CONTRADICTORY,
                            "history:" + record.raw.source_ref + ".cumulative_quote",
                            str(report.cumulative_quote),
                            str(observed.cumulative_quote),
                        )
                    )
                equivalent = observed == report
        return equivalent

    for record in projection.normalized:
        if record.raw.source_ref in selected or not _matches(
            record.raw.scope, replay.plan.query.identity
        ):
            continue
        equivalent = history(record)
        # Ordem de recepção local serve só para bloquear novidades não avaliadas,
        # não para escolher automaticamente um terminal ou inferir cronologia Binance.
        if positions[record.raw.source_ref] > last_selected and not equivalent:
            findings.append(
                SellReconciliationFinding(
                    C.FILL_SET_INCOMPLETE, K.UNCONFIRMED, "late:" + record.raw.source_ref
                )
            )
    return reconcile_sell_terminal(
        replay.book,
        cycle,
        projection.ledger,
        report,
        collection,
        source_findings=tuple(findings),
        journal_reference=journal_reference,
    )
