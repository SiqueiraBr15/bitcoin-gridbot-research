"""A17: avaliação pura, sem FinalizedSell enquanto binding/completude estão pendentes.

Concordância entre observações é necessária, mas não prova que a fonte externa
está completa. Achados nunca autorizam liberação, crédito, reenvio ou avanço.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from gridbot.application.operational_grid import GridOperationalBook
from gridbot.application.sell_evidence import (
    CollectedSellTrade,
    ObservedSellOrderReport,
    SellCollectionStopReason,
    SellEvidenceError,
    SellEvidenceErrorCode,
    SellOrderIdentity,
    SellTradeCollection,
    SellTradeIdentityCoverage,
    SellTradePagination,
    _guard,
    _nested,
    _typed,
)
from gridbot.application.sell_fills import (
    SellFillError,
    SellFillErrorCode,
    SellFillLedger,
    validate_sell_fill_ledger_against_book,
)
from gridbot.domain.assets import Symbol
from gridbot.domain.decimals import financial
from gridbot.domain.enums import OrderStatus, OrderType, Side
from gridbot.domain.values import Money, Price, Qty
from gridbot.strategy.grid_state import CellCycleRef


class SellFindingKind(StrEnum):
    CONTRADICTORY = "CONTRADICTORY"
    MISSING = "MISSING"
    UNCONFIRMED = "UNCONFIRMED"
    INFORMATION = "INFORMATION"


class SellReconciliationCode(StrEnum):
    ORDER_BINDING_MISSING = "ORDER_BINDING_MISSING"
    ORDER_BINDING_STRUCTURALLY_VERIFIED = "ORDER_BINDING_STRUCTURALLY_VERIFIED"
    EXTERNAL_IDENTITY_UNAUTHENTICATED = "EXTERNAL_IDENTITY_UNAUTHENTICATED"
    COLLECTION_QUERY_MISSING = "COLLECTION_QUERY_MISSING"
    COLLECTION_SCOPE_MISMATCH = "COLLECTION_SCOPE_MISMATCH"
    CAPTURE_MISMATCH = "CAPTURE_MISMATCH"
    QUERY_LIMIT_INVALID = "QUERY_LIMIT_INVALID"
    NATIVE_CURSOR_INVALID = "NATIVE_CURSOR_INVALID"
    CURSOR_ADVANCE_INVALID = "CURSOR_ADVANCE_INVALID"
    COLLECTION_POSSIBLY_TRUNCATED = "COLLECTION_POSSIBLY_TRUNCATED"
    ORDER_BINDING_UNCONFIRMED = "ORDER_BINDING_UNCONFIRMED"
    EXTERNAL_COMPLETENESS_UNCONFIRMED = "EXTERNAL_COMPLETENESS_UNCONFIRMED"
    STALE_OPERATIONAL_BOOK = "STALE_OPERATIONAL_BOOK"
    ORDER_REPORT_MISSING = "ORDER_REPORT_MISSING"
    ORDER_IDENTITY_MISMATCH = "ORDER_IDENTITY_MISMATCH"
    EXECUTION_REF_MISMATCH = "EXECUTION_REF_MISMATCH"
    CYCLE_MISMATCH = "CYCLE_MISMATCH"
    SYMBOL_MISMATCH = "SYMBOL_MISMATCH"
    SIDE_MISMATCH = "SIDE_MISMATCH"
    ORDER_TYPE_MISMATCH = "ORDER_TYPE_MISMATCH"
    ORIGINAL_QUANTITY_MISMATCH = "ORIGINAL_QUANTITY_MISMATCH"
    LIMIT_PRICE_MISMATCH = "LIMIT_PRICE_MISMATCH"
    EXECUTED_QUANTITY_MISMATCH = "EXECUTED_QUANTITY_MISMATCH"
    CUMULATIVE_QUOTE_MISMATCH = "CUMULATIVE_QUOTE_MISMATCH"
    FIELD_MISSING = "FIELD_MISSING"
    UNKNOWN_EXECUTION_STATUS = "UNKNOWN_EXECUTION_STATUS"
    NON_TERMINAL_ORDER = "NON_TERMINAL_ORDER"
    TERMINAL_STATUS_CONFLICT = "TERMINAL_STATUS_CONFLICT"
    TERMINAL_STATUS_POLICY_UNCONFIRMED = "TERMINAL_STATUS_POLICY_UNCONFIRMED"
    ORDER_TERMINAL_NO_FILL = "ORDER_TERMINAL_NO_FILL"
    PARTIAL_TERMINAL_EXECUTION = "PARTIAL_TERMINAL_EXECUTION"
    FULL_TERMINAL_EXECUTION = "FULL_TERMINAL_EXECUTION"
    FILL_SET_INCOMPLETE = "FILL_SET_INCOMPLETE"
    TRADE_SET_MISMATCH = "TRADE_SET_MISMATCH"
    TRADE_ID_CONFLICT = "TRADE_ID_CONFLICT"
    TRADE_FIELD_MISMATCH = "TRADE_FIELD_MISMATCH"
    NON_TRADE_OBSERVATION = "NON_TRADE_OBSERVATION"
    QUOTE_DISCREPANCY = "QUOTE_DISCREPANCY"
    FEE_EVIDENCE_INCOMPLETE = "FEE_EVIDENCE_INCOMPLETE"
    FEE_MISMATCH = "FEE_MISMATCH"
    BASE_FEE_EXCEEDS_HOLD = "BASE_FEE_EXCEEDS_HOLD"
    QUOTE_FEE_EXCEEDS_PROCEEDS = "QUOTE_FEE_EXCEEDS_PROCEEDS"
    OVERFILL = "OVERFILL"
    COLLECTION_MISSING = "COLLECTION_MISSING"
    COLLECTION_NOT_EXHAUSTED = "COLLECTION_NOT_EXHAUSTED"
    PAGE_CHAIN_INCOMPLETE = "PAGE_CHAIN_INCOMPLETE"
    PAGE_SOURCE_CONFLICT = "PAGE_SOURCE_CONFLICT"
    COLLECTION_CHANGED = "COLLECTION_CHANGED"
    THIRD_ASSET_FEE_UNVALUED = "THIRD_ASSET_FEE_UNVALUED"


type FindingValue = Qty | Price | Money | Symbol | CellCycleRef | str | tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class SellReconciliationFinding:
    code: SellReconciliationCode
    kind: SellFindingKind
    source: str
    expected: FindingValue = None
    observed: FindingValue = None

    def __post_init__(self) -> None:
        with _guard():
            _typed(self.code, SellReconciliationCode)
            _typed(self.kind, SellFindingKind)
            _typed(self.source, str)
            for value in (self.expected, self.observed):
                if value is None or isinstance(value, str):
                    continue
                if isinstance(value, tuple):
                    for item in value:
                        _typed(item, str)
                elif isinstance(value, (Qty, Price, Money, Symbol, CellCycleRef)):
                    _nested(value, type(value))
                else:
                    raise TypeError("valor de diagnóstico inválido")


class SellReconciliationState(StrEnum):
    PENDING_EVIDENCE = "PENDING_EVIDENCE"
    CONTRADICTORY_EVIDENCE = "CONTRADICTORY_EVIDENCE"


class SellObservedOutcome(StrEnum):
    UNDETERMINED = "UNDETERMINED"
    TERMINAL_NO_FILL_OBSERVED = "TERMINAL_NO_FILL_OBSERVED"
    PARTIAL_TERMINAL_EXECUTION_OBSERVED = "PARTIAL_TERMINAL_EXECUTION_OBSERVED"
    FULL_TERMINAL_EXECUTION_OBSERVED = "FULL_TERMINAL_EXECUTION_OBSERVED"


class SellBindingVerification(StrEnum):
    ROOT_UNVERIFIED = "ROOT_UNVERIFIED"
    MISSING = "MISSING"
    CONFLICTING = "CONFLICTING"
    LOCALLY_CONSISTENT = "LOCALLY_CONSISTENT"
    STRUCTURALLY_MATCHED = "STRUCTURALLY_MATCHED"


class SellCollectionVerification(StrEnum):
    ROOT_UNVERIFIED = "ROOT_UNVERIFIED"
    NOT_PROVIDED = "NOT_PROVIDED"
    INSUFFICIENT_METADATA = "INSUFFICIENT_METADATA"
    INCONSISTENT = "INCONSISTENT"
    STRUCTURALLY_COHERENT = "STRUCTURALLY_COHERENT"


C = SellReconciliationCode
K = SellFindingKind


def _evaluate(
    book: GridOperationalBook,
    ledger: SellFillLedger,
    report: ObservedSellOrderReport | None,
    collection: SellTradeCollection | None,
) -> tuple[SellReconciliationFinding, ...]:
    """Revalida antes de diagnóstico/no-op. Precisão falha com erro, nunca pending."""
    with _guard():
        _typed(book, GridOperationalBook)
        _typed(ledger, SellFillLedger)
        replace(ledger)
        if report is not None:
            _nested(report, ObservedSellOrderReport)
        if collection is not None:
            _nested(collection, SellTradeCollection)
        findings: list[SellReconciliationFinding] = []

        def add(
            code: SellReconciliationCode,
            kind: SellFindingKind,
            source: str,
            expected: FindingValue = None,
            observed: FindingValue = None,
        ) -> None:
            findings.append(SellReconciliationFinding(code, kind, source, expected, observed))

        def compare(
            code: SellReconciliationCode,
            source: str,
            expected: FindingValue,
            observed: FindingValue,
        ) -> None:
            if observed is None:
                add(C.FIELD_MISSING, K.MISSING, source, expected)
            elif expected != observed:
                add(code, K.CONTRADICTORY, source, expected, observed)

        def identity(
            identity: SellOrderIdentity,
            source: str,
            coverage: SellTradeIdentityCoverage = SellTradeIdentityCoverage.FULL_DECLARED_IDENTITY,
        ) -> None:
            compare(
                C.SYMBOL_MISMATCH,
                source + ".symbol",
                ledger.context.symbol,
                identity.symbol,
            )
            compare(
                C.CYCLE_MISMATCH, source + ".cycle", ledger.context.cycle_ref, identity.cycle_ref
            )
            compare(
                C.EXECUTION_REF_MISMATCH,
                source + ".execution",
                ledger.context.execution_ref.value,
                identity.execution_ref.value,
            )
            expected_identity = (
                binding.identity
                if binding is not None
                else (report.identity if report is not None else None)
            )
            if (
                expected_identity is not None
                and coverage is SellTradeIdentityCoverage.ORDER_ID_WITHOUT_CLIENT_ID
            ):
                expected_identity = replace(expected_identity, client_order_ref=None)
            if expected_identity is not None and identity != expected_identity:
                add(
                    C.ORDER_IDENTITY_MISMATCH,
                    K.CONTRADICTORY,
                    source,
                    _identity_key(expected_identity),
                    _identity_key(identity),
                )

        # Vínculo estrutural nunca autentica a origem nem prova ausência de fills tardios.
        binding = None
        add(C.EXTERNAL_IDENTITY_UNAUTHENTICATED, K.UNCONFIRMED, "ingestion")
        add(C.EXTERNAL_COMPLETENESS_UNCONFIRMED, K.UNCONFIRMED, "ingestion")
        try:
            validate_sell_fill_ledger_against_book(ledger, book)
            binding = book.external_binding_for(ledger.context.cycle_ref)
        except SellFillError as exc:
            if exc.code is SellFillErrorCode.FINANCIAL_PRECISION_ERROR:
                raise SellEvidenceError(
                    SellEvidenceErrorCode.FINANCIAL_PRECISION_ERROR, str(exc)
                ) from exc
            add(C.STALE_OPERATIONAL_BOOK, K.UNCONFIRMED, "book", observed=exc.code.value)
        if binding is None:
            add(C.ORDER_BINDING_MISSING, K.MISSING, "book.binding")
            add(C.ORDER_BINDING_UNCONFIRMED, K.UNCONFIRMED, "A15")
        else:
            add(C.ORDER_BINDING_STRUCTURALLY_VERIFIED, K.INFORMATION, "book.binding")

        qty = ledger.gross_executed_qty
        quote = ledger.gross_observed_quote
        requested = ledger.context.requested_qty
        for fill in ledger.fills:
            if fill.observed_quote != fill.derived_quote_notional:
                add(
                    C.QUOTE_DISCREPANCY,
                    K.CONTRADICTORY,
                    "ledger:" + fill.fill_ref,
                    fill.derived_quote_notional,
                    fill.observed_quote,
                )
        for fee in ledger.third_asset_fees:
            if fee.amount > 0:
                add(
                    C.THIRD_ASSET_FEE_UNVALUED,
                    K.INFORMATION,
                    "ledger:" + fee.asset.code,
                    observed=fee,
                )

        if report is None:
            add(C.ORDER_REPORT_MISSING, K.MISSING, "report")
        else:
            identity(report.identity, "report")
            compare(C.SIDE_MISMATCH, "report.side", Side.SELL.value, report.side.value)
            compare(
                C.ORDER_TYPE_MISMATCH, "report.type", OrderType.LIMIT.value, report.order_type.value
            )
            compare(
                C.ORIGINAL_QUANTITY_MISMATCH, "report.original_qty", requested, report.original_qty
            )
            compare(
                C.LIMIT_PRICE_MISMATCH,
                "report.limit",
                ledger.context.limit_price,
                report.limit_price,
            )
            compare(
                C.EXECUTED_QUANTITY_MISMATCH, "report.executed", qty, report.cumulative_executed_qty
            )
            compare(C.CUMULATIVE_QUOTE_MISMATCH, "report.quote", quote, report.cumulative_quote)
            status = report.status
            if status is None:
                add(C.UNKNOWN_EXECUTION_STATUS, K.UNCONFIRMED, "report.status")
            elif not status.is_terminal:
                add(C.NON_TERMINAL_ORDER, K.UNCONFIRMED, "report.status", observed=status.value)
            elif (status is OrderStatus.FILLED and report.cumulative_executed_qty != requested) or (
                status is OrderStatus.REJECTED and report.cumulative_executed_qty != Qty.zero()
            ):
                # Ausência permanece missing, não uma contradição inventada.
                if report.cumulative_executed_qty is not None:
                    add(
                        C.TERMINAL_STATUS_CONFLICT,
                        K.CONTRADICTORY,
                        "report.status",
                        requested if status is OrderStatus.FILLED else Qty.zero(),
                        report.cumulative_executed_qty,
                    )
            elif report.cumulative_executed_qty == qty:
                if qty.is_zero:
                    add(C.ORDER_TERMINAL_NO_FILL, K.INFORMATION, "report.status")
                elif qty < requested:
                    add(C.PARTIAL_TERMINAL_EXECUTION, K.INFORMATION, "report.status")
                elif status is OrderStatus.FILLED:
                    add(C.FULL_TERMINAL_EXECUTION, K.INFORMATION, "report.status")
                else:
                    add(
                        C.TERMINAL_STATUS_POLICY_UNCONFIRMED,
                        K.UNCONFIRMED,
                        "report.status",
                        observed=status.value,
                    )

        if collection is None:
            add(C.COLLECTION_MISSING, K.MISSING, "collection")
            return tuple(findings)
        identity(collection.identity, "collection")
        query = collection.query
        native = query is not None and query.pagination is SellTradePagination.BINANCE_FROM_ID
        if query is None:
            add(C.COLLECTION_QUERY_MISSING, K.MISSING, "collection.query")
        else:
            identity(query.identity, "collection.query")
            if query.identity != collection.identity:
                add(C.COLLECTION_SCOPE_MISMATCH, K.CONTRADICTORY, "collection.query.identity")
            if report is None or report.collection_ref is None:
                add(C.FIELD_MISSING, K.MISSING, "report.collection_ref")
            elif report.collection_ref != query.collection_ref:
                add(C.CAPTURE_MISMATCH, K.CONTRADICTORY, "report.collection_ref")
            if native and query.identity.venue_ref != "BINANCE_SPOT":
                add(C.COLLECTION_SCOPE_MISMATCH, K.CONTRADICTORY, "collection.query.venue")
            if query.limit is None:
                add(C.FIELD_MISSING, K.MISSING, "collection.query.limit")
            elif native and query.limit > 1000:
                add(C.QUERY_LIMIT_INVALID, K.CONTRADICTORY, "collection.query.limit")
            if collection.pages and collection.pages[0].cursor_from != query.initial_cursor:
                add(C.PAGE_CHAIN_INCOMPLETE, K.CONTRADICTORY, "collection.query.start")
            if native and query.initial_cursor != "0":
                add(C.PAGE_CHAIN_INCOMPLETE, K.UNCONFIRMED, "collection.start.bound")
        if collection.stop_reason is not SellCollectionStopReason.NO_MORE_RESULTS:
            add(
                C.COLLECTION_NOT_EXHAUSTED,
                K.UNCONFIRMED,
                "collection.stop",
                observed=collection.stop_reason.value,
            )
        if not collection.pages:
            add(C.PAGE_CHAIN_INCOMPLETE, K.MISSING, "collection.pages")
        elif not native and collection.pages[0].cursor_from is not None:
            add(
                C.PAGE_CHAIN_INCOMPLETE,
                K.UNCONFIRMED,
                "collection.start",
                observed=collection.pages[0].cursor_from,
            )
        seen_sources: set[str] = set()
        cursors: set[str] = set()
        trades: dict[str, CollectedSellTrade] = {}
        previous_cursor: str | None = None
        for index, page in enumerate(collection.pages):
            if query is not None:
                if page.query_identity is None:
                    add(C.FIELD_MISSING, K.MISSING, "page:" + page.source_ref + ".identity")
                else:
                    identity(page.query_identity, "page:" + page.source_ref + ".identity")
                    if page.query_identity != query.identity:
                        add(C.COLLECTION_SCOPE_MISMATCH, K.CONTRADICTORY, "page:" + page.source_ref)
                if page.collection_ref is None:
                    add(C.FIELD_MISSING, K.MISSING, "page:" + page.source_ref + ".capture")
                elif page.collection_ref != query.collection_ref:
                    add(C.CAPTURE_MISMATCH, K.CONTRADICTORY, "page:" + page.source_ref)
                if page.requested_limit is None:
                    add(C.FIELD_MISSING, K.MISSING, "page:" + page.source_ref + ".limit")
                elif page.requested_limit != query.limit or len(page.trades) > page.requested_limit:
                    add(C.QUERY_LIMIT_INVALID, K.CONTRADICTORY, "page:" + page.source_ref)
                if native:
                    cursor = _native_id(page.cursor_from)
                    ids = tuple(_native_id(t.trade_ref) for t in page.trades)
                    next_id = _native_id(page.next_cursor)
                    if (
                        cursor is None
                        or any(i is None for i in ids)
                        or (page.next_cursor is not None and next_id is None)
                    ):
                        add(C.NATIVE_CURSOR_INVALID, K.CONTRADICTORY, "page:" + page.source_ref)
                    else:
                        valid_ids = tuple(i for i in ids if i is not None)
                        if any(i < cursor for i in valid_ids):
                            add(
                                C.CURSOR_ADVANCE_INVALID, K.CONTRADICTORY, "page:" + page.source_ref
                            )
                        if next_id is not None and (
                            not valid_ids or next_id <= cursor or next_id != max(valid_ids) + 1
                        ):
                            add(
                                C.CURSOR_ADVANCE_INVALID, K.CONTRADICTORY, "page:" + page.source_ref
                            )
                    if (
                        page.next_cursor is None
                        and page.requested_limit is not None
                        and (len(page.trades) >= page.requested_limit)
                    ):
                        add(
                            C.COLLECTION_POSSIBLY_TRUNCATED,
                            K.UNCONFIRMED,
                            "page:" + page.source_ref,
                        )
            if page.source_ref in seen_sources:
                add(C.PAGE_SOURCE_CONFLICT, K.CONTRADICTORY, "page:" + page.source_ref)
            seen_sources.add(page.source_ref)
            if index and (previous_cursor is None or page.cursor_from != previous_cursor):
                add(
                    C.PAGE_CHAIN_INCOMPLETE,
                    K.UNCONFIRMED,
                    "page:" + page.source_ref,
                    previous_cursor,
                    page.cursor_from,
                )
            if page.next_cursor is not None:
                if page.next_cursor in cursors or page.next_cursor == page.cursor_from:
                    add(
                        C.PAGE_CHAIN_INCOMPLETE,
                        K.CONTRADICTORY,
                        "page:" + page.source_ref,
                        observed=page.next_cursor,
                    )
                cursors.add(page.next_cursor)
            previous_cursor = page.next_cursor
            for trade in page.trades:
                identity(trade.identity, "trade:" + trade.trade_ref, trade.identity_coverage)
                if trade.trade_ref in trades:
                    add(C.TRADE_ID_CONFLICT, K.CONTRADICTORY, "trade:" + trade.trade_ref)
                else:
                    trades[trade.trade_ref] = trade
        if previous_cursor is not None:
            add(C.PAGE_CHAIN_INCOMPLETE, K.UNCONFIRMED, "collection.end", observed=previous_cursor)
        for label, snapshot in (
            ("before", collection.order_before),
            ("after", collection.order_after),
        ):
            if snapshot is None:
                add(C.FIELD_MISSING, K.MISSING, "collection." + label)
            else:
                identity(snapshot.identity, "collection." + label)
                if query is not None:
                    if snapshot.collection_ref is None:
                        add(C.FIELD_MISSING, K.MISSING, "collection." + label + ".capture")
                    elif snapshot.collection_ref != query.collection_ref:
                        add(C.CAPTURE_MISMATCH, K.CONTRADICTORY, "collection." + label)
                if report is not None and replace(
                    snapshot, source_ref=None, collection_ref=None
                ) != (replace(report, source_ref=None, collection_ref=None)):
                    add(C.COLLECTION_CHANGED, K.UNCONFIRMED, "collection." + label)

        expected_refs = {fill.fill_ref for fill in ledger.fills}
        observed_refs = set(trades)
        missing = tuple(sorted(expected_refs - observed_refs))
        extra = tuple(sorted(observed_refs - expected_refs))
        if missing:
            add(C.FILL_SET_INCOMPLETE, K.MISSING, "collection.trades", missing)
        if extra:
            add(C.TRADE_SET_MISMATCH, K.CONTRADICTORY, "collection.trades", observed=extra)
        fills = {fill.fill_ref: fill for fill in ledger.fills}
        for trade_ref in sorted(trades):
            trade = trades[trade_ref]
            source = "trade:" + trade_ref
            compare(C.SIDE_MISMATCH, source + ".side", Side.SELL.value, trade.side.value)
            # Binance -1 é sentinel de evento sem trade; não aplica namespace numérico a outros IDs.
            if (trade.identity.venue_ref == "BINANCE_SPOT" and trade.trade_ref == "-1") or (
                trade.executed_qty is not None and trade.executed_qty.is_zero
            ):
                add(C.NON_TRADE_OBSERVATION, K.CONTRADICTORY, source)
            current_fill = fills.get(trade_ref)
            if (
                current_fill is not None
                and current_fill.liquidity is not None
                and trade.liquidity is not None
            ):
                compare(
                    C.TRADE_FIELD_MISMATCH,
                    source + ".liquidity",
                    current_fill.liquidity.value,
                    trade.liquidity.value,
                )
            for field in ("execution_price", "executed_qty", "observed_quote", "fee"):
                value = getattr(trade, field)
                if value is None:
                    add(
                        C.FEE_EVIDENCE_INCOMPLETE if field == "fee" else C.FIELD_MISSING,
                        K.MISSING,
                        source + "." + field,
                    )
                elif current_fill is not None:
                    compare(
                        C.FEE_MISMATCH if field == "fee" else C.TRADE_FIELD_MISMATCH,
                        source + "." + field,
                        getattr(current_fill, field),
                        value,
                    )
            if (
                trade.execution_price is not None
                and trade.executed_qty is not None
                and trade.observed_quote is not None
            ):
                derived = Money(
                    trade.execution_price.notional(trade.executed_qty), trade.identity.symbol.quote
                )
                if derived != trade.observed_quote:
                    add(C.QUOTE_DISCREPANCY, K.CONTRADICTORY, source, derived, trade.observed_quote)
        # Totais da coleta só quando todos os registros pertencem à identidade declarada,
        # sem duplicatas. Nunca misturar símbolos/contas nem preencher campos ausentes.
        coherent = collection.identity.symbol == ledger.context.symbol and all(
            (
                t.identity == replace(collection.identity, client_order_ref=None)
                if t.identity_coverage is SellTradeIdentityCoverage.ORDER_ID_WITHOUT_CLIENT_ID
                else t.identity == collection.identity
            )
            for t in trades.values()
        )
        unique = sum(len(p.trades) for p in collection.pages) == len(trades)
        if coherent and unique:
            if all(t.executed_qty is not None for t in trades.values()):
                total = Qty(
                    _sum(
                        tuple(
                            t.executed_qty.value
                            for t in trades.values()
                            if t.executed_qty is not None
                        )
                    )
                )
                if total > requested:
                    add(C.OVERFILL, K.CONTRADICTORY, "collection.qty", requested, total)
            if all(t.fee is not None for t in trades.values()):
                base_fee = Qty(
                    _sum(
                        tuple(
                            t.fee.amount
                            for t in trades.values()
                            if t.fee is not None and t.fee.asset == ledger.context.symbol.base
                        )
                    )
                )
                if base_fee > ledger.context.intent.base_fee_hold:
                    add(
                        C.BASE_FEE_EXCEEDS_HOLD,
                        K.CONTRADICTORY,
                        "collection.base_fee",
                        ledger.context.intent.base_fee_hold,
                        base_fee,
                    )
                if all(t.observed_quote is not None for t in trades.values()):
                    gross = Money(
                        _sum(
                            tuple(
                                t.observed_quote.amount
                                for t in trades.values()
                                if t.observed_quote is not None
                            )
                        ),
                        ledger.context.symbol.quote,
                    )
                    fee_quote = Money(
                        _sum(
                            tuple(
                                t.fee.amount
                                for t in trades.values()
                                if t.fee is not None and t.fee.asset == ledger.context.symbol.quote
                            )
                        ),
                        ledger.context.symbol.quote,
                    )
                    if fee_quote.amount > gross.amount:
                        add(
                            C.QUOTE_FEE_EXCEEDS_PROCEEDS,
                            K.CONTRADICTORY,
                            "collection.quote_fee",
                            gross,
                            fee_quote,
                        )
        return tuple(findings)


def _sum(values: tuple[Decimal, ...]) -> Decimal:
    with financial():
        return sum(values, Decimal(0))


def _native_id(value: str | None) -> int | None:
    """IDs nativos canônicos ASCII; não impõe namespace numérico aos DTOs legados.

    Limite lexical evita conversão de strings arbitrariamente grandes, sem pressupor
    contiguidade entre IDs. next_cursor é derivação do coletor, não resposta Binance.
    """
    if value is None or not 1 <= len(value) <= 20 or not value.isascii() or not value.isdecimal():
        return None
    if len(value) > 1 and value[0] == "0":
        return None
    return int(value)


def _identity_key(identity: SellOrderIdentity) -> tuple[str, ...]:
    # None não é convertido para ID real vazio: tupla carrega presença separadamente.
    return (
        identity.venue_ref,
        identity.account_ref,
        identity.environment_ref,
        identity.symbol.base.code,
        identity.symbol.quote.code,
        identity.order_ref,
        "absent" if identity.client_order_ref is None else "present",
        "" if identity.client_order_ref is None else identity.client_order_ref,
        identity.execution_ref.value,
        str(identity.cycle_ref),
    )


@dataclass(frozen=True, slots=True)
class SellReconciliationAssessment:
    book: GridOperationalBook
    ledger: SellFillLedger
    report: ObservedSellOrderReport | None
    collection: SellTradeCollection | None

    def __post_init__(self) -> None:
        _ = self.findings

    @property
    def findings(self) -> tuple[SellReconciliationFinding, ...]:
        return _evaluate(self.book, self.ledger, self.report, self.collection)

    @property
    def state(self) -> SellReconciliationState:
        if any(f.kind is K.CONTRADICTORY for f in self.findings):
            return SellReconciliationState.CONTRADICTORY_EVIDENCE
        return SellReconciliationState.PENDING_EVIDENCE

    @property
    def binding_verification(self) -> SellBindingVerification:
        findings = self.findings
        codes = {f.code for f in findings}
        if C.STALE_OPERATIONAL_BOOK in codes:
            return SellBindingVerification.ROOT_UNVERIFIED
        if C.ORDER_BINDING_MISSING in codes:
            return SellBindingVerification.MISSING
        if codes & {
            C.ORDER_IDENTITY_MISMATCH,
            C.SYMBOL_MISMATCH,
            C.CYCLE_MISMATCH,
            C.EXECUTION_REF_MISMATCH,
            C.SIDE_MISMATCH,
        }:
            return SellBindingVerification.CONFLICTING
        if (
            self.report is None
            or self.collection is None
            or any(f.kind is K.MISSING for f in findings)
        ):
            return SellBindingVerification.LOCALLY_CONSISTENT
        return SellBindingVerification.STRUCTURALLY_MATCHED

    @property
    def collection_verification(self) -> SellCollectionVerification:
        if self.collection is None:
            return SellCollectionVerification.NOT_PROVIDED
        findings = self.findings
        if any(f.code is C.STALE_OPERATIONAL_BOOK for f in findings):
            return SellCollectionVerification.ROOT_UNVERIFIED
        relevant = tuple(
            f for f in findings if f.source.startswith(("collection", "page:", "trade:", "report"))
        )
        if any(f.kind is K.CONTRADICTORY for f in relevant):
            return SellCollectionVerification.INCONSISTENT
        if any(f.kind in (K.MISSING, K.UNCONFIRMED) for f in relevant):
            return SellCollectionVerification.INSUFFICIENT_METADATA
        return SellCollectionVerification.STRUCTURALLY_COHERENT

    @property
    def observed_outcome(self) -> SellObservedOutcome:
        findings = self.findings
        if any(f.kind is K.CONTRADICTORY or f.code is C.STALE_OPERATIONAL_BOOK for f in findings):
            return SellObservedOutcome.UNDETERMINED
        codes = {f.code for f in findings}
        if C.ORDER_TERMINAL_NO_FILL in codes:
            return SellObservedOutcome.TERMINAL_NO_FILL_OBSERVED
        if C.PARTIAL_TERMINAL_EXECUTION in codes:
            return SellObservedOutcome.PARTIAL_TERMINAL_EXECUTION_OBSERVED
        if C.FULL_TERMINAL_EXECUTION in codes:
            return SellObservedOutcome.FULL_TERMINAL_EXECUTION_OBSERVED
        return SellObservedOutcome.UNDETERMINED


def assess_sell_finalization(
    book: GridOperationalBook,
    ledger: SellFillLedger,
    report: ObservedSellOrderReport | None,
    collection: SellTradeCollection | None = None,
) -> SellReconciliationAssessment:
    """Uma avaliação não é finalização e não é autoridade econômica."""
    return SellReconciliationAssessment(book, ledger, report, collection)
