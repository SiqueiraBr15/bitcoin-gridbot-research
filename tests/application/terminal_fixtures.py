"""Fontes sintéticas A8-A17.1 com identidade real do contrato, sem adapter."""

from __future__ import annotations

from decimal import Decimal

from gridbot.application.operational_grid import GridOperationalBook
from gridbot.application.sell_evidence import (
    ObservedSellOrderReport,
    SellCollectionStopReason,
    SellTradeCollection,
    SellTradePage,
)
from gridbot.application.sell_fills import SellFillLedger, record_sell_fill
from gridbot.domain import USDT, Asset, Money, OrderStatus, Qty
from tests.application.test_external_sell_identity import native_scenario
from tests.application.test_sell_fills import fill
from tests.application.test_sell_reconciliation import report, trade


def terminal_sources(
    status: OrderStatus | None = OrderStatus.FILLED,
    qty: str = ".031",
    *,
    n: int = 1,
    fee: str = ".01",
    asset: Asset = USDT,
) -> tuple[GridOperationalBook, SellFillLedger, ObservedSellOrderReport, SellTradeCollection]:
    root, original, _report, collection = native_scenario()
    ledger = SellFillLedger(original.context)
    if Decimal(qty):
        quantity = Decimal(qty) / Decimal(n)
        commission = Decimal(fee) / Decimal(n)
        for index in range(n):
            ledger = record_sell_fill(
                ledger,
                fill(
                    ledger,
                    fill_ref=str(101 + index * 3),
                    executed_qty=Qty(quantity),
                    observed_quote=Money(quantity * Decimal(105), USDT),
                    fee=Money(commission, asset),
                ),
            )
    terminal = report(ledger, status=status, collection_ref="capture-1")
    query = collection.query
    assert query is not None
    pages = []
    cursor = "0"
    for start in range(0, len(ledger.fills), 10):
        trades = tuple(trade(ledger, index) for index in range(start, min(start + 10, n)))
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
    pages.append(
        SellTradePage("page-empty", cursor, None, (), query.identity, query.collection_ref, 10)
    )
    collection = SellTradeCollection(
        query.identity,
        tuple(pages),
        SellCollectionStopReason.NO_MORE_RESULTS,
        terminal,
        terminal,
        query,
    )
    return root, ledger, terminal, collection
