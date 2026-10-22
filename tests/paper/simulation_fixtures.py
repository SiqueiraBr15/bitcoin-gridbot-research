"""Supplied commands only, shared by differential tests and opt-in capacity runs."""

from decimal import Decimal
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
from gridbot.domain import (
    BTC,
    USDT,
    LiquidityRole,
    Money,
    OrderStatus,
    OrderType,
    Price,
    Qty,
    Side,
)
from gridbot.paper.accounting import (
    PaperInitialState,
    PaperPrepareBuy,
    PaperPrepareSell,
    PaperSellAuthorization,
    PaperSellEvidence,
)
from gridbot.portfolio import (
    BuyExecutionContext,
    BuyExecutionRef,
    BuyExecutionStatus,
    BuyFillLedger,
    BuyFillReconciliationEvidence,
    FinalizedBuy,
    ObservedBuyFill,
    ObservedBuyTerminalReport,
    finalize_buy,
)
from gridbot.strategy import CellCycleRef, GridState, build_buy_intents, size_grid_buys


class PaperReader(Protocol):
    @property
    def initial(self) -> PaperInitialState: ...

    @property
    def grid_state(self) -> GridState: ...

    def buy_context(self, ref: CellCycleRef) -> BuyExecutionContext: ...

    def sell_authorization(self, ref: SellExecutionRef) -> PaperSellAuthorization: ...


def buy_command(
    source: PaperReader, cell: int = 0, *, budget: str = "10", hold: str = ".01"
) -> PaperPrepareBuy:
    state = source.grid_state
    plan = build_buy_intents(
        state, size_grid_buys(state, source.initial.rules, Money.parse(budget, USDT))
    )
    ref = state.cells[cell].cycle_ref
    return PaperPrepareBuy(
        plan,
        ref,
        Money.parse(hold, USDT),
        BuyExecutionRef(f"{source.initial.account.ref}:BUY:{cell}-{ref.cycle_seq}"),
    )


def buy_fill_result(
    source: PaperReader,
    cell: int = 0,
    *,
    fee: Money | None = None,
    qty: Qty | None = None,
) -> FinalizedBuy:
    ref = source.grid_state.cells[cell].cycle_ref
    context = source.buy_context(ref)
    quantity = context.intent.qty if qty is None else qty
    ledger = BuyFillLedger(context.intent).record(
        ObservedBuyFill(
            f"{source.initial.account.ref}:TRADE:BUY-{cell}-{ref.cycle_seq}",
            ref,
            context.symbol,
            context.intent.price,
            quantity,
            Money.parse(".000032", BTC) if fee is None else fee,
            LiquidityRole.TAKER,
        )
    )
    refs = tuple(f.fill_ref for f in ledger.fills)
    status = (
        BuyExecutionStatus.FILLED if quantity == context.intent.qty else BuyExecutionStatus.CANCELED
    )
    return finalize_buy(
        context,
        ledger,
        ObservedBuyTerminalReport(
            context.execution_ref, context.symbol, ref, status, quantity, refs
        ),
        BuyFillReconciliationEvidence(context.execution_ref, context.symbol, ref, quantity, refs),
    )


def sell_command(source: PaperReader, cell: int = 0, *, hold: str = ".0001") -> PaperPrepareSell:
    ref = source.grid_state.cells[cell].cycle_ref
    prefix = source.initial.account.ref
    return PaperPrepareSell(
        ref,
        Qty.parse(hold),
        SellExecutionRef(f"{prefix}:SELL:{cell}-{ref.cycle_seq}"),
        f"{prefix}:ORDER:{cell}-{ref.cycle_seq}",
    )


def sell_source(
    source: PaperReader,
    execution: SellExecutionRef,
    *,
    status: OrderStatus | None = OrderStatus.FILLED,
    qty: Qty | None = None,
    fees: tuple[Money, ...] = (Money.parse(".01", USDT),),
    price: str = "105",
) -> PaperSellEvidence:
    authorization = source.sell_authorization(execution)
    context, identity = authorization.context, authorization.identity
    quantity = context.requested_qty if qty is None else qty
    fills = []
    if not quantity.is_zero:
        part = Qty(quantity.value / Decimal(len(fees)))
        for index, fee in enumerate(fees):
            execution_price = Price.parse(price)
            fills.append(
                ObservedSellFill(
                    execution,
                    f"{source.initial.account.ref}:TRADE:{execution.value}-fill-{index}",
                    context.cycle_ref,
                    context.symbol,
                    execution_price,
                    part,
                    Money(execution_price.notional(part), USDT),
                    fee,
                )
            )
    fills.sort(key=lambda f: f.fill_ref)
    gross = sum((f.observed_quote for f in fills), Money.zero(USDT))
    report = ObservedSellOrderReport(
        identity,
        status,
        context.requested_qty,
        quantity,
        gross,
        context.limit_price,
        Side.SELL,
        OrderType.LIMIT,
        "paper-terminal",
        "paper-capture",
    )
    trades = tuple(
        CollectedSellTrade(
            identity,
            f.fill_ref,
            f.execution_price,
            f.executed_qty,
            f.observed_quote,
            f.fee,
            Side.SELL,
        )
        for f in fills
    )
    query = SellTradeQueryScope(
        identity, "paper-capture", SellTradePagination.DECLARED_CHAIN, None, 100
    )
    pages = (
        (SellTradePage("paper-page", None, "end", trades, identity, "paper-capture", 100),)
        if trades
        else ()
    )
    cursor = "end" if trades else None
    pages = (*pages, SellTradePage("empty", cursor, None, (), identity, "paper-capture", 100))
    collection = SellTradeCollection(
        identity, pages, SellCollectionStopReason.NO_MORE_RESULTS, report, report, query
    )
    return PaperSellEvidence(
        source.initial.account,
        authorization.revision,
        SellTerminalReconciliation(
            authorization.witness,
            context.cycle_ref,
            SellFillLedger(context, tuple(fills)),
            report,
            collection,
        ),
    )
