"""Modèle indépendant: SQL brut, JSON stdlib, SHA et Fraction sans codec de production."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from fractions import Fraction
from pathlib import Path
from typing import Any

from gridbot.application.operational_persistence import VersionedOperationalState


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def audit_rows(path: Path, *, expected_receipts: int | None = None) -> None:
    connection = sqlite3.connect(path, autocommit=True)
    try:
        connection.execute("BEGIN")
        assert connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        assert connection.execute("SELECT * FROM meta").fetchall() == [(1, 1, 1)]
        references = set()
        raw_count = 0
        for key, scope_text, revision, seq, tip in connection.execute("SELECT * FROM heads"):
            assert key == digest(scope_text)
            revisions = connection.execute(
                "SELECT revision,state_digest,last_sequence,tip_hash FROM revisions "
                "WHERE scope_key=? ORDER BY revision",
                (key,),
            ).fetchall()
            entries = connection.execute(
                "SELECT sequence,revision,kind,payload,previous_hash,digest,source_key "
                "FROM entries WHERE scope_key=? ORDER BY sequence",
                (key,),
            ).fetchall()
            assert [r[0] for r in revisions] == list(range(revision + 1))
            assert [e[0] for e in entries] == list(range(1, seq + 1))
            previous = "0" * 64
            for number, rev, kind, payload, parent, signature, source in entries:
                assert previous == parent
                envelope = {
                    "schema": 1,
                    "value": {"tuple": [key, number, rev, kind, payload, parent, source]},
                }
                text = json.dumps(
                    envelope, ensure_ascii=True, sort_keys=True, separators=(",", ":")
                )
                assert digest(text) == signature
                previous = signature
                raw_count += kind == "RAW"
                assert type(json.loads(payload)) is dict
            assert previous == tip
            previous_root = None
            for rev, state_digest, last, revision_tip in revisions:
                references.add(state_digest)
                payload = connection.execute(
                    "SELECT payload FROM states WHERE digest=?", (state_digest,)
                ).fetchone()
                assert payload is not None
                assert digest(payload[0]) == state_digest
                own = [e for e in entries if e[1] == rev]
                assert own
                assert own[-1][0] == last
                assert own[-1][5] == revision_tip
                if rev and all(e[2] in {"RAW", "REPLAY"} for e in own):
                    assert state_digest == previous_root
                previous_root = state_digest
            assert revisions[-1][2:] == (seq, tip)
        assert references == {r[0] for r in connection.execute("SELECT digest FROM states")}
        if expected_receipts is not None:
            assert raw_count == expected_receipts
    finally:
        connection.close()


def audit_assets(state: VersionedOperationalState, *, initial: int = 20) -> None:
    funded = state.book.inventory_book.funded_buy_book
    spent = Fraction()
    for buy in funded.lifecycle.consumed:
        for fill in buy.ledger.fills:
            spent += Fraction(fill.execution_price.value) * Fraction(fill.executed_qty.value)
            if fill.fee.asset.code == "USDT":
                spent += Fraction(fill.fee.amount)
    held = sum(
        (
            Fraction(r.intent.price.value) * Fraction(r.intent.qty.value)
            + Fraction(r.quote_fee_hold.amount)
            for r in funded.reservations
        ),
        Fraction(),
    )
    assert Fraction(funded.initial_quote_capital.amount) == initial
    assert Fraction(funded.spent_quote.amount) == spent
    assert Fraction(funded.reserved_quote.amount) == held
    assert Fraction(funded.available_quote.amount) == initial - spent - held
    for reservation in state.book.inventory_book.reservations:
        buy = reservation.finalized_buy
        net = sum(
            (
                Fraction(f.executed_qty.value)
                - (Fraction(f.fee.amount) if f.fee.asset.code == "BTC" else 0)
                for f in buy.ledger.fills
            ),
            Fraction(),
        )
        step = Fraction(reservation.assessment.market_rules.quantity.step_size.value)
        qty = (net // step) * step
        hold = Fraction(reservation.base_fee_hold.value)
        assert Fraction(reservation.reserved_sell_qty.value) == qty
        assert qty + hold <= net
        assert Fraction(reservation.unreserved_base_qty.value) == net - qty - hold
    assert all(cell.cycle_seq == 0 for cell in state.book.grid_state.cells)


def audit_observed(replay: Any) -> None:
    ledger = replay.projection.ledger
    if ledger is None:
        return
    fills = ledger.fills
    x = sum((Fraction(f.executed_qty.value) for f in fills), Fraction())
    b = sum((Fraction(f.fee.amount) for f in fills if f.fee.asset.code == "BTC"), Fraction())
    y = sum((Fraction(f.observed_quote.amount) for f in fills), Fraction())
    u = sum((Fraction(f.fee.amount) for f in fills if f.fee.asset.code == "USDT"), Fraction())
    origin = ledger.context.intent.finalized_buy.ledger.fills
    n = sum(
        (
            Fraction(f.executed_qty.value)
            - (Fraction(f.fee.amount) if f.fee.asset.code == "BTC" else 0)
            for f in origin
        ),
        Fraction(),
    )
    q = Fraction(ledger.context.requested_qty.value)
    h = Fraction(ledger.context.intent.base_fee_hold.value)
    assert x <= q
    assert b <= h
    assert x + b <= q + h <= n
    assert Fraction(ledger.net_observed_quote.amount) == y - u
