"""Legitimate funded BUY / reserved SELL fixtures, with explicit synthetic prices."""

from dataclasses import replace
from decimal import Decimal

from gridbot.application.sell_economics import SellEconomicAssessment
from gridbot.application.sell_evidence import SellTradeCollection, SellTradePage
from gridbot.application.sell_fills import SellFillLedger, record_sell_fill
from gridbot.application.sell_terminal import reconcile_sell_terminal
from gridbot.domain import BTC, USDT, Asset, LiquidityRole, Money, OrderStatus, Price, Qty
from tests.application.terminal_fixtures import terminal_sources
from tests.application.test_sell_fills import fill
from tests.application.test_sell_reconciliation import report, trade


def multi_buy_sources(n: int = 10, asset: Asset = BTC) -> SellEconomicAssessment:
    """Rebuild the complete funded pipeline; no patched acquisition authority."""
    from gridbot.application import (
        GridOperationalBook,
        SellInventoryBook,
        bind_external_sell_order,
        bind_sell_execution,
        build_sell_intents,
        prepare_sell,
        reserve_operational_sell,
        settle_funded_buy,
    )
    from gridbot.portfolio import (
        BuyExecutionStatus,
        BuyFillLedger,
        BuyFillReconciliationEvidence,
        ObservedBuyFill,
        ObservedBuyTerminalReport,
        finalize_buy,
    )
    from tests.application.test_external_sell_identity import binding
    from tests.application.test_operational_grid import context, ref
    from tests.application.test_sell_intents import assessment, prepare

    funded = prepare()
    attempt = funded.lifecycle.attempt_for(ref())
    assert attempt is not None
    buy = attempt.execution
    assert buy is not None
    qty = Qty(Decimal(".032") / Decimal(n))
    fee = Money(Decimal(".000032") / Decimal(n), asset)
    ledger = BuyFillLedger(buy.intent)
    for i in range(n):
        ledger = ledger.record(
            ObservedBuyFill(
                f"buy-fill-{i}", ref(), buy.symbol, buy.intent.price, qty, fee, LiquidityRole.TAKER
            )
        )
    refs = tuple(f.fill_ref for f in ledger.fills)
    final = finalize_buy(
        buy,
        ledger,
        ObservedBuyTerminalReport(
            buy.execution_ref,
            buy.symbol,
            ref(),
            BuyExecutionStatus.FILLED,
            ledger.gross_filled_qty,
            refs,
        ),
        BuyFillReconciliationEvidence(
            buy.execution_ref, buy.symbol, ref(), ledger.gross_filled_qty, refs
        ),
    )
    funded = settle_funded_buy(funded, final)
    root = GridOperationalBook(SellInventoryBook(funded))
    hold = Qty.parse(".0001") if asset == BTC else Qty.zero()
    root = reserve_operational_sell(root, assessment(root.inventory_book), hold)
    root = prepare_sell(root, build_sell_intents(root.inventory_book), ref())
    root = bind_sell_execution(root, ref(), context(root))
    root = bind_external_sell_order(root, ref(), binding(root))
    sell = root.attempt_for(ref())
    assert sell is not None
    assert sell.execution is not None
    sell_ledger = SellFillLedger(sell.execution)
    sell_ledger = record_sell_fill(
        sell_ledger,
        fill(
            sell_ledger,
            fill_ref="101",
            executed_qty=sell.execution.requested_qty,
            observed_quote=Money(Price.parse("105").notional(sell.execution.requested_qty), USDT),
            fee=Money.parse(".001", USDT),
        ),
    )
    base = economic_sources()
    provisional = SellEconomicAssessment(
        replace(base.reconciliation, book=root, ledger=sell_ledger)
    )
    return assessment_from_ledger(provisional, sell_ledger, OrderStatus.FILLED)


def assessment_from_ledger(
    original: SellEconomicAssessment, ledger: SellFillLedger, status: OrderStatus
) -> SellEconomicAssessment:
    source = original.reconciliation
    assert source.collection is not None
    query = source.collection.query
    assert query is not None
    terminal = report(ledger, status=status, collection_ref=query.collection_ref)
    pages = []
    cursor = "0"
    for start in range(0, len(ledger.fills), 10):
        trades = tuple(trade(ledger, i) for i in range(start, min(start + 10, len(ledger.fills))))
        next_cursor = str(int(trades[-1].trade_ref) + 1)
        pages.append(
            SellTradePage(
                f"page-{start}",
                cursor,
                next_cursor,
                trades,
                query.identity,
                query.collection_ref,
                10,
            )
        )
        cursor = next_cursor
    pages.append(SellTradePage("empty", cursor, None, (), query.identity, query.collection_ref, 10))
    collection = replace(
        source.collection, pages=tuple(pages), order_before=terminal, order_after=terminal
    )
    assert isinstance(collection, SellTradeCollection)
    return SellEconomicAssessment(
        replace(source, ledger=ledger, report=terminal, collection=collection)
    )


def economic_sources(
    status: OrderStatus | None = OrderStatus.FILLED,
    qty: str = ".031",
    *,
    fee: str = ".01",
    asset: Asset = USDT,
    n: int = 1,
) -> SellEconomicAssessment:
    root, ledger, terminal, collection = terminal_sources(status, qty, n=n, fee=fee, asset=asset)
    return SellEconomicAssessment(
        reconcile_sell_terminal(root, ledger.context.cycle_ref, ledger, terminal, collection)
    )


def mandatory_example() -> SellEconomicAssessment:
    initial = economic_sources()
    original = initial.reconciliation.ledger
    assert original is not None
    ledger = SellFillLedger(original.context)
    for index, (price, commission) in enumerate(
        (
            ("102", Money.parse(".00004", BTC)),
            ("105", Money.parse(".00105", USDT)),
            ("110", Money.parse(".00001", Asset("BNB"))),
        )
    ):
        qty = Qty.parse(".010")
        observed_price = Price.parse(price)
        ledger = record_sell_fill(
            ledger,
            fill(
                ledger,
                fill_ref=str(101 + 3 * index),
                executed_qty=qty,
                execution_price=observed_price,
                observed_quote=Money(observed_price.notional(qty), USDT),
                fee=commission,
            ),
        )
    return assessment_from_ledger(initial, ledger, OrderStatus.CANCELED)
