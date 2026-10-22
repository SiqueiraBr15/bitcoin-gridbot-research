"""Oráculos independentes e trajetórias limitadas; contadores de passos reais."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from fractions import Fraction

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from gridbot.application import (
    bind_external_sell_order,
    bind_sell_execution,
    mark_sell_submission_uncertain,
)
from gridbot.application.sell_lifecycle import SellAttemptStatus
from gridbot.exchange.binance.offline_replay import OfflineSellTape
from tests.application.test_external_sell_identity import binding
from tests.application.test_offline_sell_evidence import edited, replay_ledger, wire_scenario
from tests.application.test_operational_grid import context, prepared_root, ref

PS = settings(max_examples=50, deadline=None, derandomize=True)
ACTUAL_STEPS: dict[str, int] = {}


def count(name: str) -> None:
    ACTUAL_STEPS[name] = ACTUAL_STEPS.get(name, 0) + 1


@PS
@given(st.permutations((0, 1, 2)), st.integers(0, 2))
def test_replay_permutation_idempotence_preserves_original(order: list[int], repeat: int) -> None:
    original = wire_scenario()
    tape = OfflineSellTape(tuple(original.tape.observations[i] for i in order))
    tape = tape.capture(original.tape.observations[repeat])
    changed = replace(original, tape=tape)
    assert changed.projection == original.projection
    assert len(changed.tape.observations) == 4
    assert changed.book.inventory_book is original.book.inventory_book


@PS
@given(st.integers(1, 31000), st.integers(0, 100))
def test_exact_fraction_quote_conservation_and_no_credit(units: int, fee_units: int) -> None:
    qty = Decimal(units).scaleb(-6)
    quote = qty * Decimal(105)
    fee = Decimal(fee_units).scaleb(-6)
    replay = wire_scenario()
    replay = edited(
        edited(edited(replay, "page-0", "qty", str(qty)), "page-0", "quoteQty", str(quote)),
        "page-0",
        "commission",
        str(fee),
    )
    ledger = replay_ledger(replay)
    assert Fraction(ledger.gross_executed_qty.value) == Fraction(units, 1_000_000)
    assert Fraction(ledger.net_observed_quote.amount) == Fraction(
        units * 105 - fee_units, 1_000_000
    )
    assert ledger.gross_executed_qty <= ledger.context.requested_qty
    assert replay.candidate is None or units == 31000
    assert replay.book.inventory_book.funded_buy_book.spent_quote.amount > 0


@PS
@given(st.text(min_size=0, max_size=200))
def test_arbitrary_refused_json_is_retained_without_effect(payload: str) -> None:
    replay = wire_scenario()
    raw = replace(replay.tape.observations[1], payload=payload)
    changed = replace(
        replay,
        tape=OfflineSellTape((replay.tape.observations[0], raw, replay.tape.observations[2])),
    )
    _ = changed.projection
    assert changed.tape.observations[1].payload == payload
    assert changed.book is replay.book
    assert changed.tape.observations[1] is raw


@PS
@given(st.sampled_from(["account_ref", "environment_ref"]), st.integers(1, 10000))
def test_identity_scope_cannot_be_relabelled(field: str, number: int) -> None:
    replay = wire_scenario()
    raw = replay.tape.observations[1]
    scope = (
        replace(raw.scope, account_ref=f"account-{number}")
        if field == "account_ref"
        else replace(raw.scope, environment_ref=f"environment-{number}")
    )
    changed = replace(
        replay,
        tape=OfflineSellTape(
            (replay.tape.observations[0], replace(raw, scope=scope), replay.tape.observations[2])
        ),
    )
    assert changed.candidate is None
    assert changed.projection.quarantined_sources


@PS
@given(st.integers(1, 100000), st.booleans())
def test_overfill_and_missing_fee_never_promote(number: int, missing: bool) -> None:
    replay = wire_scenario()
    if missing:
        changed = edited(replay, "page-0", "commission", None, remove=True)
    else:
        changed = edited(replay, "page-0", "qty", str(Decimal(31000 + number).scaleb(-6)))
    assert changed.candidate is None
    assert changed.projection.quarantined_sources
    assert changed.book.inventory_book is replay.book.inventory_book


@PS
@given(st.permutations((0, 1, 2)))
def test_late_terminal_and_trade_converge_without_release(order: list[int]) -> None:
    replay = wire_scenario()
    tape = OfflineSellTape()
    for index in order:
        tape = tape.capture(replay.tape.observations[index])
        changed = replace(replay, tape=tape)
        if len(tape.observations) < 3:
            assert changed.candidate is None
        assert changed.book is replay.book
    assert changed.candidate is not None


class OfflineSellMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        count("initialized")
        self.source = wire_scenario()
        self.root = prepared_root()
        self.tape = OfflineSellTape()
        self.reservation = self.root.inventory_book.reservations[0]
        self.original_capital = self.root.inventory_book.funded_buy_book

    @precondition(lambda self: self.root.sell_attempts[0].status is SellAttemptStatus.PREPARED)
    @rule()
    def uncertain(self) -> None:
        count("uncertain")
        self.root = mark_sell_submission_uncertain(self.root, ref())

    @precondition(
        lambda self: self.root.sell_attempts[0].status is not SellAttemptStatus.EXECUTION_BOUND
    )
    @rule()
    def bind_internal(self) -> None:
        count("bind_internal")
        self.root = bind_sell_execution(self.root, ref(), context(self.root))

    @precondition(
        lambda self: self.root.sell_attempts[0].status is SellAttemptStatus.EXECUTION_BOUND
    )
    @rule()
    def bind_external(self) -> None:
        count("bind_external")
        self.root = bind_external_sell_order(self.root, ref(), binding(self.root))

    @rule(index=st.integers(0, 2))
    def observe_before_or_after_binding(self, index: int) -> None:
        count("observe")
        self.tape = self.tape.capture(self.source.tape.observations[index])

    @rule()
    def refused_capture_is_never_deleted(self) -> None:
        count("refused")
        raw = replace(self.source.tape.observations[1], source_ref="bad-json", payload="{")
        self.tape = self.tape.capture(raw)
        assert raw in self.tape.observations

    @rule()
    def assess_again(self) -> None:
        count("assess")
        replay = replace(self.source, book=self.root, tape=self.tape)
        assert replay.projection == replay.projection

    @invariant()
    def no_economic_effect_and_eligibility_requires_all_sources(self) -> None:
        count("invariant")
        replay = replace(self.source, book=self.root, tape=self.tape)
        candidate = replay.candidate
        assert self.root.inventory_book.reservations[0] is self.reservation
        assert self.root.inventory_book.funded_buy_book is self.original_capital
        assert self.root.grid_state.cells[0].cycle_seq == 0
        if candidate is not None:
            assert self.root.external_binding_for(ref()) is not None
            assert {r.source_ref for r in self.tape.observations} >= {"order", "page-0", "page-1"}


TestOfflineSellMachine = OfflineSellMachine.TestCase
TestOfflineSellMachine.settings = settings(
    max_examples=30, stateful_step_count=12, deadline=None, derandomize=True
)
