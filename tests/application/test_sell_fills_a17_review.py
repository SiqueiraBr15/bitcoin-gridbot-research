"""Gate 0 A17: limitação de prefixo demonstrada, sem hipótese sobre a venue."""

from __future__ import annotations

from gridbot.application import SellFillLedger, build_sell_fill_ledger, record_sell_fill
from gridbot.domain import USDT, Money
from tests.application.test_operational_grid import ref
from tests.application.test_sell_fills import E, bound_root, expect, fill
from tests.application.test_sell_intents import fingerprint


def test_prefix_rejection_does_not_discard_observation_or_change_final_set() -> None:
    root = bound_root()
    before = fingerprint(root.inventory_book)
    empty = build_sell_fill_ledger(root, ref())
    a = fill(empty, fill_ref="a", fee=Money.parse("1.06", USDT))
    b = fill(empty, fill_ref="b")
    error = expect(E.QUOTE_FEE_EXCEEDS_PROCEEDS, lambda: record_sell_fill(empty, a))
    assert error.observation is a
    assert empty.fills == ()
    batch = SellFillLedger(empty.context, (a, b))
    reverse = record_sell_fill(record_sell_fill(empty, b), a)
    assert reverse == batch
    assert reverse.gross_observed_quote == Money.parse("2.10", USDT)
    assert reverse.net_observed_quote == Money.parse("1.04", USDT)
    assert reverse.quote_discrepancy_refs == ()
    assert fingerprint(root.inventory_book) == before
