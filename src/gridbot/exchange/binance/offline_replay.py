"""Replay de fontes declaradas. Sem cronologia econômica inferida ou settlement."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import DecimalException

from gridbot.application.operational_grid import GridOperationalBook
from gridbot.application.sell_candidate import SellCandidateEligibility, SellFinalizationCandidate
from gridbot.application.sell_evidence import (
    CollectedSellTrade,
    ObservedSellOrderReport,
    SellCollectionStopReason,
    SellEvidenceError,
    SellEvidenceErrorCode,
    SellOrderIdentity,
    SellTradeCollection,
    SellTradePage,
    SellTradeQueryScope,
    _nested,
    _ref,
    _typed,
)
from gridbot.application.sell_fills import (
    ObservedSellFill,
    SellFillError,
    SellFillLedger,
    build_sell_fill_ledger,
)
from gridbot.application.sell_reconciliation import (
    SellReconciliationAssessment,
    assess_sell_finalization,
)
from gridbot.application.sell_terminal import SellTerminalReconciliation
from gridbot.domain.enums import OrderStatus
from gridbot.domain.errors import DomainError
from gridbot.domain.values import Qty
from gridbot.exchange.binance.offline_evidence import (
    NormalizedSellObservation,
    OfflineIssueCode,
    OfflineSellIssue,
    OfflineSellSource,
    RawSellObservation,
    normalize_sell_observation,
)


@dataclass(frozen=True, slots=True)
class OfflineSellTape:
    observations: tuple[RawSellObservation, ...] = ()

    def __post_init__(self) -> None:
        _typed(self.observations, tuple)
        for observation in self.observations:
            _typed(observation, RawSellObservation)
            replace(observation)

    def capture(self, observation: RawSellObservation) -> OfflineSellTape:
        """Não normaliza. Preserva até payload inválido, repetido e conflitante."""
        replace(self)
        replace(observation)
        return OfflineSellTape((*self.observations, observation))


@dataclass(frozen=True, slots=True)
class OfflineSellReplayPlan:
    query: SellTradeQueryScope
    report_ref: str
    before_ref: str
    after_ref: str
    page_refs: tuple[str, ...]
    stop_reason: SellCollectionStopReason
    event_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _nested(self.query, SellTradeQueryScope)
        _typed(self.stop_reason, SellCollectionStopReason)
        for refs in (self.page_refs, self.event_refs):
            _typed(refs, tuple)
            if len(set(refs)) != len(refs):
                raise DomainError("referências repetidas no plano")
            for ref in refs:
                _ref(ref)
        for ref in (self.report_ref, self.before_ref, self.after_ref):
            _ref(ref)
        if set(self.page_refs) & set(self.event_refs):
            raise DomainError("uma fonte não pode ser simultaneamente página e evento")


@dataclass(frozen=True, slots=True)
class OfflineSellProjection:
    """Resultado derivado, não fonte autorizadora. Fontes vivem no replay/tape."""

    normalized: tuple[NormalizedSellObservation, ...]
    issues: tuple[OfflineSellIssue, ...]
    quarantined_sources: tuple[str, ...]
    ledger: SellFillLedger | None
    assessment: SellReconciliationAssessment | None


def _matches(actual: SellOrderIdentity, expected: SellOrderIdentity, trade: bool = False) -> bool:
    # myTrades não informa client ID. Chave composta da ordem continua obrigatória;
    # ID de cliente explicitamente presente jamais é ignorado.
    comparable = (
        replace(expected, client_order_ref=None)
        if trade and actual.client_order_ref is None
        else expected
    )
    return actual == comparable


def _economic_trade(trade: CollectedSellTrade) -> tuple[object, ...]:
    return (
        trade.execution_price,
        trade.executed_qty,
        trade.observed_quote,
        trade.fee,
        trade.side,
        trade.liquidity,
    )


def _project(
    book: GridOperationalBook, tape: OfflineSellTape, plan: OfflineSellReplayPlan
) -> OfflineSellProjection:
    replace(tape)
    replace(plan)
    unique: dict[str, RawSellObservation] = {}
    conflicts: set[str] = set()
    issues: list[OfflineSellIssue] = []
    quarantine: set[str] = set()

    def issue(code: OfflineIssueCode, ref: str, field: str, detail: str) -> None:
        issues.append(OfflineSellIssue(code, ref, field, detail))
        if code is not OfflineIssueCode.SOURCE_NOT_SELECTED:
            quarantine.add(ref)

    for raw in tape.observations:
        existing = unique.get(raw.source_ref)
        if existing is not None and existing != raw:
            conflicts.add(raw.source_ref)
        else:
            unique[raw.source_ref] = raw
    for ref in sorted(conflicts):
        issue(
            OfflineIssueCode.RAW_CONFLICT,
            ref,
            "raw",
            "mesma referência, conteúdos/metadados distintos",
        )
        del unique[ref]
    normalized = tuple(normalize_sell_observation(unique[ref]) for ref in sorted(unique))
    records = {n.raw.source_ref: n for n in normalized}
    selected = {plan.report_ref, plan.before_ref, plan.after_ref, *plan.page_refs, *plan.event_refs}
    for ref in sorted(selected - records.keys() - conflicts):
        issue(OfflineIssueCode.MISSING, ref, "source", "fonte selecionada ausente")
    expected = plan.query.identity
    active: dict[str, NormalizedSellObservation] = {}
    for normalized_record in normalized:
        ref = normalized_record.raw.source_ref
        if ref not in selected:
            issue(
                OfflineIssueCode.SOURCE_NOT_SELECTED,
                ref,
                "plan",
                "raw retido; não selecionado nesta avaliação",
            )
            if (
                normalized_record.raw.scope == expected
                and normalized_record.raw.collection_ref == plan.query.collection_ref
                and (
                    normalized_record.issues
                    or normalized_record.trades
                    or normalized_record.report is not None
                    or normalized_record.raw.kind is OfflineSellSource.MY_TRADES_PAGE
                )
            ):
                issue(
                    OfflineIssueCode.UNASSESSED_SOURCE,
                    ref,
                    "plan",
                    "captura atual contém fonte financeira/recusada não avaliada",
                )
            continue
        if normalized_record.issues:
            issues.extend(normalized_record.issues)
            quarantine.add(ref)
        if normalized_record.raw.scope != expected:
            issue(
                OfflineIssueCode.IDENTITY_CONFLICT,
                ref,
                "scope",
                "scope declarado difere da consulta",
            )
        if normalized_record.raw.collection_ref != plan.query.collection_ref:
            issue(
                OfflineIssueCode.IDENTITY_CONFLICT,
                ref,
                "capture",
                "fonte selecionada pertence a outra captura ou captura ausente",
            )
        if normalized_record.report is not None and not _matches(
            normalized_record.report.identity, expected
        ):
            issue(
                OfflineIssueCode.IDENTITY_CONFLICT,
                ref,
                "report.identity",
                "ordem/conta/ambiente/ciclo incompatível",
            )
        if any(not _matches(t.identity, expected, True) for t in normalized_record.trades):
            issue(
                OfflineIssueCode.IDENTITY_CONFLICT,
                ref,
                "trade.identity",
                "trade fora da ordem selecionada",
            )
        if ref not in quarantine:
            active[ref] = normalized_record

    base = None
    try:
        base = build_sell_fill_ledger(book, expected.cycle_ref)
        binding = book.external_binding_for(expected.cycle_ref)
        if binding is None or binding.identity != expected:
            issue(
                OfflineIssueCode.IDENTITY_CONFLICT,
                "book",
                "binding",
                "binding não corresponde ao plano",
            )
    except SellFillError as exc:
        code = OfflineIssueCode.ROOT_UNAVAILABLE
        if exc.code.value == "FINANCIAL_PRECISION_ERROR":
            code = OfflineIssueCode.FINANCIAL_PRECISION_ERROR
        issue(code, "book", "root", exc.code.value)
    if base is None:
        return OfflineSellProjection(
            normalized, tuple(issues), tuple(sorted(quarantine)), None, None
        )

    def report(ref: str) -> ObservedSellOrderReport | None:
        record = active.get(ref)
        if record is None:
            return None
        if record.raw.kind is OfflineSellSource.MY_TRADES_PAGE or record.report is None:
            issue(OfflineIssueCode.MISSING, ref, "report", "fonte não contém relatório")
            return None
        return record.report

    terminal = report(plan.report_ref)
    before = report(plan.before_ref)
    after = report(plan.after_ref)
    pages: list[SellTradePage] = []
    candidates: dict[str, list[tuple[str, CollectedSellTrade]]] = {}
    # Um executionReport usado como report/snapshot também contém uma observação
    # de trade: selecionar só sua parte terminal não pode esconder fee/quote conflitante.
    event_refs = set(plan.event_refs) | {
        ref
        for ref in (plan.report_ref, plan.before_ref, plan.after_ref)
        if ref in active and active[ref].raw.kind is OfflineSellSource.EXECUTION_REPORT
    }
    for ref in (*plan.page_refs, *sorted(event_refs)):
        record = active.get(ref)
        if record is None:
            continue
        page = ref in plan.page_refs
        if page and record.raw.kind is not OfflineSellSource.MY_TRADES_PAGE:
            issue(OfflineIssueCode.MALFORMED, ref, "kind", "página exige fonte myTrades")
            continue
        if not page and record.raw.kind is not OfflineSellSource.EXECUTION_REPORT:
            issue(OfflineIssueCode.MALFORMED, ref, "kind", "evento exige executionReport")
            continue
        if not page:
            event_report = record.report
            if event_report is None:
                issue(OfflineIssueCode.MISSING, ref, "event.report", "relatório do evento ausente")
                continue
            for name, observed, authorized in (
                ("side", event_report.side, base.context.side),
                ("type", event_report.order_type, base.context.order_type),
                ("original_qty", event_report.original_qty, base.context.requested_qty),
                ("limit", event_report.limit_price, base.context.limit_price),
            ):
                if observed != authorized:
                    issue(
                        OfflineIssueCode.IDENTITY_CONFLICT,
                        ref,
                        "event." + name,
                        f"autorizado={authorized}; observado={observed}",
                    )
            event_qty = event_report.cumulative_executed_qty
            event_quote = event_report.cumulative_quote
            if event_qty is not None and event_quote is not None:
                try:
                    minimum_quote = base.context.limit_price.notional(event_qty)
                    if event_quote.amount < minimum_quote or (
                        event_qty.is_zero and event_quote.amount != 0
                    ):
                        issue(
                            OfflineIssueCode.TRADE_CONFLICT,
                            ref,
                            "event.quote_qty",
                            f"quantidade={event_qty}; mínimo={minimum_quote}; quote={event_quote}",
                        )
                except DecimalException as exc:
                    issue(
                        OfflineIssueCode.FINANCIAL_PRECISION_ERROR,
                        ref,
                        "event.quote_qty",
                        type(exc).__name__,
                    )
            if event_qty is not None and (
                event_qty > base.context.requested_qty
                or (
                    event_report.status is OrderStatus.FILLED
                    and event_qty != base.context.requested_qty
                )
                or (event_report.status is OrderStatus.REJECTED and event_qty != Qty.zero())
            ):
                issue(
                    OfflineIssueCode.TRADE_CONFLICT,
                    ref,
                    "event.status_qty",
                    "status/quantidade cumulativa incompatíveis",
                )
            for observed_trade in record.trades:
                if (
                    event_qty is not None
                    and observed_trade.executed_qty is not None
                    and observed_trade.executed_qty > event_qty
                ):
                    issue(
                        OfflineIssueCode.TRADE_CONFLICT,
                        ref,
                        "event.executed",
                        f"último={observed_trade.executed_qty}; cumulativo={event_qty}",
                    )
                if (
                    event_quote is not None
                    and observed_trade.observed_quote is not None
                    and observed_trade.observed_quote.amount > event_quote.amount
                ):
                    issue(
                        OfflineIssueCode.TRADE_CONFLICT,
                        ref,
                        "event.quote",
                        f"último={observed_trade.observed_quote}; cumulativo={event_quote}",
                    )
            if terminal is not None and terminal.status is not None and terminal.status.is_terminal:
                if (
                    event_report.status is not None
                    and event_report.status.is_terminal
                    and event_report.status is not terminal.status
                ):
                    issue(
                        OfflineIssueCode.TRADE_CONFLICT,
                        ref,
                        "event.terminal_status",
                        f"evento={event_report.status}; terminal={terminal.status}",
                    )
                if (
                    event_qty is not None
                    and terminal.cumulative_executed_qty is not None
                    and event_qty > terminal.cumulative_executed_qty
                ):
                    issue(
                        OfflineIssueCode.TRADE_CONFLICT,
                        ref,
                        "event.terminal_qty",
                        f"evento={event_qty}; terminal={terminal.cumulative_executed_qty}",
                    )
                if (
                    event_quote is not None
                    and terminal.cumulative_quote is not None
                    and event_quote.amount > terminal.cumulative_quote.amount
                ):
                    issue(
                        OfflineIssueCode.TRADE_CONFLICT,
                        ref,
                        "event.terminal_quote",
                        f"evento={event_quote}; terminal={terminal.cumulative_quote}",
                    )
            if ref in quarantine:
                continue
        if page:
            pages.append(
                SellTradePage(
                    ref,
                    record.raw.cursor_from,
                    record.raw.next_cursor,
                    record.trades,
                    record.raw.scope,
                    record.raw.collection_ref,
                    record.raw.requested_limit,
                )
            )
        for trade in record.trades:
            candidates.setdefault(trade.trade_ref, []).append((ref, trade))
    fills: list[ObservedSellFill] = []
    for trade_ref in sorted(candidates):
        variants = candidates[trade_ref]
        first = variants[0][1]
        # Fontes são equivalentes somente com campos econômicos/role exatos e
        # mesma chave composta já confrontada. Não mescla registros incompletos.
        if any(_economic_trade(t) != _economic_trade(first) for _, t in variants):
            for ref, _ in variants:
                issue(
                    OfflineIssueCode.TRADE_CONFLICT,
                    ref,
                    "trade:" + trade_ref,
                    "valores financeiros/role divergentes",
                )
            continue
        if (
            first.execution_price is None
            or first.executed_qty is None
            or first.observed_quote is None
            or first.fee is None
        ):
            for ref, _ in variants:
                issue(OfflineIssueCode.MISSING, ref, "trade:" + trade_ref, "financeiro incompleto")
            continue
        try:
            fills.append(
                ObservedSellFill(
                    base.context.execution_ref,
                    trade_ref,
                    expected.cycle_ref,
                    expected.symbol,
                    first.execution_price,
                    first.executed_qty,
                    first.observed_quote,
                    first.fee,
                    first.liquidity,
                    first.side,
                )
            )
        except SellFillError as exc:
            for ref, _ in variants:
                issue(
                    OfflineIssueCode.FINANCIAL_QUARANTINE, ref, "trade:" + trade_ref, exc.code.value
                )
    ledger = base
    try:
        # Batch: valida todos os fills conhecidos conjuntamente. Nunca escolhe
        # um subconjunto que esconda overfill ou déficit de comissão.
        ledger = SellFillLedger(base.context, tuple(fills))
    except SellFillError as exc:
        for ref in sorted({ref for variants in candidates.values() for ref, _ in variants}):
            issue(OfflineIssueCode.FINANCIAL_QUARANTINE, ref, "batch", exc.code.value)
    collection = SellTradeCollection(
        expected, tuple(pages), plan.stop_reason, before, after, plan.query
    )
    assessment = None
    try:
        assessment = assess_sell_finalization(book, ledger, terminal, collection)
    except SellEvidenceError as exc:
        if exc.code is not SellEvidenceErrorCode.FINANCIAL_PRECISION_ERROR:
            raise
        issue(
            OfflineIssueCode.FINANCIAL_PRECISION_ERROR, "assessment", "calculation", exc.code.value
        )
    return OfflineSellProjection(
        normalized, tuple(issues), tuple(sorted(quarantine)), ledger, assessment
    )


@dataclass(frozen=True, slots=True)
class OfflineSellReplay:
    book: GridOperationalBook
    tape: OfflineSellTape
    plan: OfflineSellReplayPlan

    def __post_init__(self) -> None:
        _typed(self.book, GridOperationalBook)
        replace(self.tape)
        replace(self.plan)

    @property
    def projection(self) -> OfflineSellProjection:
        return _project(self.book, self.tape, self.plan)

    @property
    def candidate(self) -> SellFinalizationCandidate | None:
        projection = self.projection
        if projection.quarantined_sources or projection.assessment is None:
            return None
        eligibility = SellCandidateEligibility(projection.assessment)
        if not eligibility.is_structurally_eligible:
            return None
        return SellFinalizationCandidate(projection.assessment)

    @property
    def terminal_reconciliation(self) -> SellTerminalReconciliation:
        from gridbot.exchange.binance.offline_terminal import reconcile_offline_sell_terminal

        return reconcile_offline_sell_terminal(self)


def replay_sell_observations(
    book: GridOperationalBook,
    tape: OfflineSellTape,
    plan: OfflineSellReplayPlan,
) -> OfflineSellReplay:
    return OfflineSellReplay(book, tape, plan)
