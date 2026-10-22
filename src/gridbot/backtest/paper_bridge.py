"""Construct native supplied-fill evidence; PAPER performs every economic transition."""

from typing import Protocol

from gridbot.application.sell_evidence import (
    CollectedSellTrade,
    ObservedSellOrderReport,
    SellCollectionStopReason,
    SellTradeCollection,
    SellTradePage,
    SellTradePagination,
    SellTradeQueryScope,
)
from gridbot.application.sell_fills import ObservedSellFill, SellFillLedger
from gridbot.application.sell_lifecycle import SellExecutionRef
from gridbot.application.sell_terminal import SellTerminalReconciliation
from gridbot.backtest.data import check
from gridbot.backtest.execution import VirtualOrder
from gridbot.domain import USDT, LiquidityRole, Money, OrderStatus, OrderType, Qty, Side
from gridbot.paper.accounting import (
    PaperApplySell,
    PaperCommand,
    PaperCostStudy,
    PaperInitialState,
    PaperObserveSell,
    PaperReleaseNoFill,
    PaperSellAuthorization,
    PaperSellEvidence,
    PaperSettleBuy,
)
from gridbot.portfolio import (
    BuyExecutionContext,
    BuyExecutionStatus,
    BuyFillLedger,
    BuyFillReconciliationEvidence,
    FinalizedBuy,
    ObservedBuyFill,
    ObservedBuyTerminalReport,
    finalize_buy,
)
from gridbot.strategy import CellCycleRef


class PaperExecutor(Protocol):
    """Only the native financial operations used to supply synthetic evidence."""

    @property
    def initial(self) -> PaperInitialState: ...

    @property
    def revision(self) -> int: ...

    def buy_context(self, ref: CellCycleRef) -> BuyExecutionContext: ...

    def sell_authorization(self, ref: SellExecutionRef) -> PaperSellAuthorization: ...

    def apply(self, expected_revision: int, command: PaperCommand) -> int: ...


def settle_buy(
    sim: PaperExecutor, order: VirtualOrder, qty: Qty, fee: Money | None, role: LiquidityRole
) -> FinalizedBuy:
    trade_ref = (
        f"{sim.initial.account.ref}:TRADE:BUY-"
        f"{order.cycle_ref.cell_index}-{order.cycle_ref.cycle_seq}"
    )
    context = sim.buy_context(order.cycle_ref)
    check(
        order.side is Side.BUY
        and order.ref == context.execution_ref.value
        and order.limit == context.intent.price
        and order.qty == context.intent.qty,
        "virtual BUY context mismatch",
    )
    ledger = BuyFillLedger(context.intent)
    if not qty.is_zero:
        if fee is None:
            raise ValueError("positive BUY needs an explicitly simulated commission")
        ledger = ledger.record(
            ObservedBuyFill(trade_ref, order.cycle_ref, context.symbol, order.limit, qty, fee, role)
        )
    else:
        check(fee is None, "no-fill BUY cannot carry a fabricated fee")
    refs = tuple(f.fill_ref for f in ledger.fills)
    status = BuyExecutionStatus.FILLED if qty == order.qty else BuyExecutionStatus.CANCELED
    result = finalize_buy(
        context,
        ledger,
        ObservedBuyTerminalReport(
            context.execution_ref, context.symbol, order.cycle_ref, status, qty, refs
        ),
        BuyFillReconciliationEvidence(
            context.execution_ref, context.symbol, order.cycle_ref, qty, refs
        ),
    )
    sim.apply(sim.revision, PaperSettleBuy(result))
    return result


def settle_sell(
    sim: PaperExecutor, order: VirtualOrder, qty: Qty, fee: Money | None, role: LiquidityRole
) -> PaperSellEvidence:
    trade_ref = (
        f"{sim.initial.account.ref}:TRADE:SELL-"
        f"{order.cycle_ref.cell_index}-{order.cycle_ref.cycle_seq}"
    )
    execution = SellExecutionRef(order.ref)
    authorization = sim.sell_authorization(execution)
    context, identity = authorization.context, authorization.identity
    check(
        order.side is Side.SELL
        and order.cycle_ref == context.cycle_ref
        and order.limit == context.limit_price
        and order.qty == context.requested_qty,
        "virtual SELL context mismatch",
    )
    fills: tuple[ObservedSellFill, ...] = ()
    trades: tuple[CollectedSellTrade, ...] = ()
    quote = Money(order.limit.notional(qty), USDT)
    if not qty.is_zero:
        if fee is None:
            raise ValueError("positive SELL requires an explicitly simulated commission")
        fills = (
            ObservedSellFill(
                execution,
                trade_ref,
                order.cycle_ref,
                context.symbol,
                order.limit,
                qty,
                quote,
                fee,
                role,
            ),
        )
        trades = (
            CollectedSellTrade(identity, trade_ref, order.limit, qty, quote, fee, Side.SELL, role),
        )
    else:
        check(fee is None, "no-fill SELL cannot carry a fabricated fee")
    capture = order.ref + ":CAPTURE"
    report = ObservedSellOrderReport(
        identity,
        OrderStatus.FILLED if qty == order.qty else OrderStatus.CANCELED,
        context.requested_qty,
        qty,
        quote,
        context.limit_price,
        Side.SELL,
        OrderType.LIMIT,
        order.ref + ":REPORT",
        capture,
    )
    pages = (
        (SellTradePage(order.ref + ":PAGE", None, "end", trades, identity, capture, 100),)
        if trades
        else ()
    )
    pages = (
        *pages,
        SellTradePage(
            order.ref + ":EMPTY", "end" if trades else None, None, (), identity, capture, 100
        ),
    )
    query = SellTradeQueryScope(identity, capture, SellTradePagination.DECLARED_CHAIN, None, 100)
    collection = SellTradeCollection(
        identity, pages, SellCollectionStopReason.NO_MORE_RESULTS, report, report, query
    )
    evidence = PaperSellEvidence(
        sim.initial.account,
        authorization.revision,
        SellTerminalReconciliation(
            authorization.witness,
            order.cycle_ref,
            SellFillLedger(context, fills),
            report,
            collection,
        ),
    )
    revision = sim.apply(sim.revision, PaperObserveSell(evidence))
    sim.apply(sim.revision, PaperApplySell(execution, revision))
    if qty.is_zero:
        sim.apply(sim.revision, PaperReleaseNoFill(execution))
    return evidence


def proportional_study(evidence: PaperSellEvidence) -> tuple[Money | None, tuple[str, ...]]:
    study = PaperCostStudy(evidence)
    # The report needs native consumption PnL, not three additional component-cost
    # divisions. Each detailed getter rebuilds the same nested evidence repeatedly.
    pnl = study.hypothetical_pnl
    limitations: tuple[str, ...] = (
        "PROPORTIONAL_NET_LOT_HYPOTHESIS_NOT_FISCAL_POLICY",
        "SEPARATE_COMPONENT_COST_PRECISION_NOT_EVALUATED",
    )
    if pnl is None:
        limitations = (*limitations, "NATIVE_PNL_UNDETERMINED")
    return pnl, limitations
