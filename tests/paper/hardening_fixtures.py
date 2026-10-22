"""Canonical fixtures and an independent raw-fill oracle for PAPER hardening."""

import hashlib
import sqlite3
from contextlib import closing
from fractions import Fraction
from pathlib import Path

from gridbot.domain import BTC, USDT
from gridbot.paper.accounting import (
    PaperApplySell,
    PaperBook,
    PaperObserveSell,
    PaperPrepareBuy,
    PaperSettleBuy,
)
from gridbot.storage.paper_codec import encode_command
from gridbot.storage.paper_journal import PaperJournal
from tests.paper.fixtures import bought, evidence, initial, prepare_buy, reserve_sell


def raw_oracle(book: PaperBook) -> dict[str, Fraction]:
    spent = Fraction()
    acquired = Fraction()
    proceeds = Fraction()
    consumed = Fraction()
    holds = {}
    for command in book.entries:
        if isinstance(command, PaperPrepareBuy):
            intent = next(i for i in command.plan.intents if i.cycle_ref == command.cycle_ref)
            holds[command.cycle_ref] = Fraction(intent.price.value) * Fraction(
                intent.qty.value
            ) + Fraction(command.quote_fee_hold.amount)
        elif isinstance(command, PaperSettleBuy):
            holds.pop(command.finalized.cycle_ref)
            for fill in command.finalized.ledger.fills:
                spent += Fraction(fill.execution_price.value) * Fraction(fill.executed_qty.value)
                acquired += Fraction(fill.executed_qty.value)
                if fill.fee.asset == USDT:
                    spent += Fraction(fill.fee.amount)
                if fill.fee.asset == BTC:
                    acquired -= Fraction(fill.fee.amount)
        elif isinstance(command, PaperApplySell):
            selected = book.entries[command.evidence_revision - 1]
            assert isinstance(selected, PaperObserveSell)
            ledger = selected.evidence.reconciliation.ledger
            assert ledger is not None
            for sell_fill in ledger.fills:
                consumed += Fraction(sell_fill.executed_qty.value)
                proceeds += Fraction(sell_fill.observed_quote.amount)
                if sell_fill.fee.asset == BTC:
                    consumed += Fraction(sell_fill.fee.amount)
                if sell_fill.fee.asset == USDT:
                    proceeds -= Fraction(sell_fill.fee.amount)
    held = sum(holds.values(), Fraction())
    available = Fraction(book.initial.initial_quote.amount) + proceeds - spent - held
    assert available >= 0
    assert acquired >= consumed
    assert Fraction(book.available_quote.amount) == available
    assert Fraction(book.buy_spending.amount) == spent
    assert Fraction(book.active_buy_reservations.amount) == held
    assert Fraction(book.settled_sell_proceeds.amount) == proceeds
    assert Fraction(book.remaining_grid_base.value) == acquired - consumed
    assert book.reserved_grid_base <= book.remaining_grid_base
    return dict(
        available=available, spent=spent, holds=held, proceeds=proceeds, btc=acquired - consumed
    )


def seeded_history(directory: Path, count: int) -> PaperJournal:
    """SQL creates test input, not a public ingestion API; recover validates every source.

    Counts >=3 contain three authorized BUY/SELL preparation events, followed by
    repeated legitimate observations. Above-cap inputs must be refused in full.
    """
    original = initial()
    store = PaperJournal.create(directory, original)
    if count == 0:
        return store
    if count == 1:
        entries = prepare_buy(original).entries
    else:
        prepared, execution = reserve_sell(bought(original))
        observation = PaperObserveSell(evidence(prepared, execution, status=None))
        entries = (*prepared.entries, *((observation,) * (count - 3)))
    path = directory / "gridbot-paper.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        previous = connection.execute("SELECT digest FROM paper_meta").fetchone()[0]
        encoded = {id(command): encode_command(command) for command in entries}
        for sequence, command in enumerate(entries, 1):
            payload = encoded[id(command)]
            digest = hashlib.sha256(f"{sequence}\n{previous}\n{payload}".encode()).hexdigest()
            connection.execute(
                "INSERT INTO paper_events VALUES(?,?,?,?)", (sequence, payload, previous, digest)
            )
            previous = digest
    return store
