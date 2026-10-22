"""Legitimate grid geometry and explicitly synthetic, namespaced executions."""

from gridbot.application.sell_evidence import (
    CollectedSellTrade,
    ObservedSellOrderReport,
    SellCollectionStopReason,
    SellTradeCollection,
    SellTradePage,
    SellTradePagination,
    SellTradeQueryScope,
)
from gridbot.application.sell_fills import ObservedSellFill
from gridbot.application.sell_lifecycle import SellExecutionRef
from gridbot.domain import (
    BTC,
    USDT,
    Asset,
    LiquidityRole,
    Money,
    OrderStatus,
    OrderType,
    Price,
    Qty,
    Side,
)
from gridbot.paper.accounting import (
    PaperAccount,
    PaperApplySell,
    PaperBook,
    PaperInitialState,
    PaperObserveSell,
    PaperPrepareBuy,
    PaperPrepareSell,
    PaperSellEvidence,
    PaperSettleBuy,
    build_paper_sell_evidence,
    paper_transition,
)
from gridbot.portfolio import (
    BuyExecutionRef,
    BuyExecutionStatus,
    BuyFillLedger,
    BuyFillReconciliationEvidence,
    FinalizedBuy,
    ObservedBuyFill,
    ObservedBuyTerminalReport,
    finalize_buy,
)
from gridbot.strategy import build_buy_intents, size_grid_buys
from tests.application.test_sell_intents import grid, rules


def initial(funding: tuple[Money, ...] = ()) -> PaperBook:
    return PaperBook(
        PaperInitialState(
            PaperAccount("PAPER:demo"), grid(), rules(), Money.parse("20", USDT), funding
        )
    )


def commit(book: PaperBook, command: object) -> PaperBook:
    from typing import cast

    from gridbot.paper.accounting import PaperCommand

    return paper_transition(book, book.revision, cast(PaperCommand, command))


def prepare_buy(book: PaperBook, cell: int = 0, budget: str = "10") -> PaperBook:
    state = book.grid_state
    plan = build_buy_intents(
        state, size_grid_buys(state, book.initial.rules, Money.parse(budget, USDT))
    )
    ref = state.cells[cell].cycle_ref
    execution = BuyExecutionRef(f"PAPER:demo:BUY:{cell}-{ref.cycle_seq}")
    return commit(book, PaperPrepareBuy(plan, ref, Money.parse(".01", USDT), execution))


def buy_result(
    book: PaperBook, cell: int = 0, asset: Asset = BTC, fee: str = ".000032"
) -> FinalizedBuy:
    ref = book.grid_state.cells[cell].cycle_ref
    context = book.buy_context(ref)
    ledger = BuyFillLedger(context.intent).record(
        ObservedBuyFill(
            f"PAPER:demo:TRADE:BUY-{cell}-{ref.cycle_seq}",
            ref,
            context.symbol,
            context.intent.price,
            context.intent.qty,
            Money.parse(fee, asset),
            LiquidityRole.TAKER,
        )
    )
    refs = tuple(f.fill_ref for f in ledger.fills)
    return finalize_buy(
        context,
        ledger,
        ObservedBuyTerminalReport(
            context.execution_ref,
            context.symbol,
            ref,
            BuyExecutionStatus.FILLED,
            ledger.gross_filled_qty,
            refs,
        ),
        BuyFillReconciliationEvidence(
            context.execution_ref, context.symbol, ref, ledger.gross_filled_qty, refs
        ),
    )


def bought(book: PaperBook | None = None, *, asset: Asset = BTC, fee: str = ".000032") -> PaperBook:
    book = prepare_buy(initial() if book is None else book)
    return commit(book, PaperSettleBuy(buy_result(book, asset=asset, fee=fee)))


def reserve_sell(
    book: PaperBook, cell: int = 0, hold: str = ".0001"
) -> tuple[PaperBook, SellExecutionRef]:
    ref = book.grid_state.cells[cell].cycle_ref
    execution = SellExecutionRef(f"PAPER:demo:SELL:{cell}-{ref.cycle_seq}")
    book = commit(
        book,
        PaperPrepareSell(
            ref, Qty.parse(hold), execution, f"PAPER:demo:ORDER:{cell}-{ref.cycle_seq}"
        ),
    )
    return book, execution


def evidence(
    book: PaperBook,
    execution: SellExecutionRef,
    *,
    status: OrderStatus | None = OrderStatus.FILLED,
    qty: str | None = None,
    fees: tuple[Money, ...] = (Money.parse(".01", USDT),),
    execution_price: str = "105",
) -> PaperSellEvidence:
    authorization = book.sell_authorization(execution)
    context, identity = authorization.context, authorization.identity
    quantity = context.requested_qty if qty is None else Qty.parse(qty)
    n = len(fees)
    fills = []
    if not quantity.is_zero:
        from decimal import Decimal

        part = Qty(quantity.value / Decimal(n))
        for index, commission in enumerate(fees):
            price = Price.parse(execution_price)
            fills.append(
                ObservedSellFill(
                    execution,
                    f"PAPER:demo:TRADE:{execution.value}-fill-{index}",
                    context.cycle_ref,
                    context.symbol,
                    price,
                    part,
                    Money(price.notional(part), USDT),
                    commission,
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
    return build_paper_sell_evidence(book, execution, tuple(fills), report, collection)


def settle_sell(
    book: PaperBook, execution: SellExecutionRef, source: PaperSellEvidence | None = None
) -> PaperBook:
    book = commit(book, PaperObserveSell(source or evidence(book, execution)))
    return commit(book, PaperApplySell(execution, book.revision))
