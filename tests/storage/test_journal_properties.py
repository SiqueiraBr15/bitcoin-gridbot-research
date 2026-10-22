"""Oráculos Fraction, transações e máquinas persistidas com contadores reais."""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import replace
from decimal import Decimal, localcontext
from pathlib import Path
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from gridbot.application.operational_persistence import (
    BindOperationalBuy,
    BindOperationalExternalSell,
    BindOperationalSell,
    MarkOperationalSellUncertain,
    PersistenceError,
    PersistenceErrorCode,
    SettleOperationalBuy,
)
from gridbot.application.sell_lifecycle import SellAttemptStatus
from gridbot.domain import BTC, USDT, Asset, Money
from gridbot.portfolio.buy_finalization import BuyExecutionContext, BuyExecutionRef
from gridbot.storage.financial_codec import revalidate_contract
from gridbot.storage.journal_models import ReceiptClassification
from gridbot.storage.journal_paths import JournalPathPolicy
from gridbot.storage.operational_journal import SQLiteOperationalJournal
from tests.application.test_external_sell_identity import binding
from tests.application.test_offline_sell_evidence import edited, wire_scenario
from tests.application.test_operational_grid import context, ref
from tests.application.test_sell_inventory import finish
from tests.storage.test_operational_journal import (
    assert_conserved,
    bound_sell,
    durable_sell,
    funded_plan,
    journal_start,
)

PS = settings(max_examples=25, deadline=None, derandomize=True)
ACTUAL_STEPS: dict[str, int] = {}


def count(name: str) -> None:
    ACTUAL_STEPS[name] = ACTUAL_STEPS.get(name, 0) + 1


@PS
@given(st.integers(-(10**20), 10**20), st.integers(-128, 128), st.booleans())
def test_decimal_sign_coefficient_and_exponent_exact(
    coefficient: int, exponent: int, negative_zero: bool
) -> None:
    count("decimal_example")
    digits = tuple(int(c) for c in str(abs(coefficient)))
    value = Decimal(
        (int(coefficient < 0 or (coefficient == 0 and negative_zero)), digits, exponent)
    )
    with localcontext() as ctx:
        ctx.prec = 2
        recovered = revalidate_contract(Money(value, USDT), Money)
        assert recovered.amount.as_tuple() == value.as_tuple()
        assert not any(ctx.flags.values())


@PS
@given(st.sampled_from([(0,), (0, 1), (0, 1, 2)]), st.sampled_from(list(SellAttemptStatus)))
def test_generated_complete_operational_graph_survives_restart(
    cells: tuple[int, ...], status: SellAttemptStatus
) -> None:
    count("graph_example")
    with tempfile.TemporaryDirectory(prefix="a17-3-graph-") as temporary:
        store, state = durable_sell(Path(temporary), cells)
        if status is SellAttemptStatus.SUBMISSION_UNCERTAIN:
            state = store.commit_operational_transition(
                state.scope, state.revision, MarkOperationalSellUncertain(ref())
            )
        elif status is SellAttemptStatus.EXECUTION_BOUND:
            state = store.commit_operational_transition(
                state.scope, state.revision, BindOperationalSell(ref(), context(state.book))
            )
            state = store.commit_operational_transition(
                state.scope, state.revision, BindOperationalExternalSell(ref(), binding(state.book))
            )
        recovered = SQLiteOperationalJournal.open(store.policy).load_operational_state(state.scope)
        assert recovered == state
        assert recovered.book.sell_attempts[0].status is status
        assert_conserved(recovered)


@PS
@given(st.integers(0, 32000), st.integers(0, 20), st.sampled_from([BTC, USDT, Asset("BNB")]))
def test_partial_buy_consumption_and_quote_conservation(
    units: int, base_fee_units: int, fee_asset: Asset
) -> None:
    count("partial_example")
    count("buy_fee_" + fee_asset.code)
    with tempfile.TemporaryDirectory(prefix="a17-3-partial-") as temporary:
        store, state = journal_start(Path(temporary))
        state = store.commit_operational_transition(state.scope, 0, funded_plan(state))
        attempt = state.book.inventory_book.funded_buy_book.lifecycle.attempt_for(ref())
        assert attempt is not None
        ctx = BuyExecutionContext(attempt.intent, BuyExecutionRef("buy-0"))
        state = store.commit_operational_transition(
            state.scope, state.revision, BindOperationalBuy(ref(), ctx)
        )
        fee = min(base_fee_units, max(0, units - 1))
        qty = None if units == 0 else str(Decimal(units).scaleb(-6))
        finalized = finish(
            state.book.inventory_book.funded_buy_book,
            qty=qty,
            fee=str(Decimal(fee).scaleb(-6)),
            asset=fee_asset,
        )
        state = store.commit_operational_transition(
            state.scope, state.revision, SettleOperationalBuy(finalized)
        )
        recovered = SQLiteOperationalJournal.open(store.policy).load_operational_state(state.scope)
        assert recovered == state
        funded = recovered.book.inventory_book.funded_buy_book
        expected_quote_units = units * 100 + (fee if fee_asset == USDT else 0)
        assert funded.spent_quote.amount == Decimal(expected_quote_units).scaleb(-6)
        assert recovered.book.inventory_book.funded_buy_book.lifecycle.consumed[
            0
        ].net_acquired_base_qty.value == Decimal(units - (fee if fee_asset == BTC else 0)).scaleb(
            -6
        )
        assert_conserved(recovered)


@PS
@given(st.sampled_from([BTC, USDT, Asset("BNB")]), st.integers(0, 8))
def test_sell_fee_assets_survive_raw_projection_and_restart(asset: Asset, fee_units: int) -> None:
    count("sell_fee_example")
    count("sell_fee_" + asset.code)
    with tempfile.TemporaryDirectory(prefix="a17-3-fees-") as temporary:
        store, state = bound_sell(Path(temporary))
        fee = Decimal(fee_units).scaleb(-5)
        source = edited(wire_scenario(), "page-0", "commissionAsset", asset.code)
        source = edited(source, "page-0", "commission", format(fee, "f"))
        state = store.append_raw_observations(state.scope, state.revision, source.tape.observations)
        state = store.record_replay(state.scope, state.revision, source.plan)
        reopened = SQLiteOperationalJournal.open(store.policy)
        replay = reopened.replay_observations(state.scope, source.plan)
        assert replay.candidate is not None
        ledger = replay.candidate.assessment.ledger
        assert ledger.fills[0].fee.asset == asset
        assert ledger.fills[0].fee.amount == fee
        assert ledger.net_observed_quote.amount == Decimal("3.255") - (fee if asset == USDT else 0)
        assert reopened.recover(state.scope).replays[-1].fills == ledger.fills
        assert_conserved(state)


@PS
@given(st.permutations((0, 1, 2)), st.integers(0, 2))
def test_late_arrival_duplicate_and_quarantine_survive_each_restart(
    order: list[int], repeated: int
) -> None:
    count("late_example")
    with tempfile.TemporaryDirectory(prefix="a17-3-late-") as temporary:
        store, state = bound_sell(Path(temporary))
        source = wire_scenario()
        for index in order:
            state = store.append_raw_observation(
                state.scope, state.revision, source.tape.observations[index]
            )
            state = store.record_replay(state.scope, state.revision, source.plan)
            store = SQLiteOperationalJournal.open(store.policy)
        original = store.recover(state.scope)
        state = store.append_raw_observation(
            state.scope, state.revision, source.tape.observations[repeated]
        )
        recovered = SQLiteOperationalJournal.open(store.policy).recover(state.scope)
        assert recovered.receipts[-1].classification is ReceiptClassification.DUPLICATE_IDENTICAL
        assert recovered.replays[: len(original.replays)] == original.replays
        assert any(record.quarantined_sources for record in original.replays[:-1])
        replay = store.replay_observations(state.scope, source.plan)
        assert replay.candidate is not None
        assert (
            len(replay.projection.ledger.fills if replay.projection.ledger is not None else ()) == 1
        )
        assert state.book == source.book
        assert_conserved(state)


@PS
@given(st.sampled_from(["before_commit", "after_event", "after_cas", "after_commit"]))
def test_fault_is_atomic_or_commit_uncertain_requires_recovery(point: str) -> None:
    count("fault_example")
    with tempfile.TemporaryDirectory(prefix="a17-3-fault-") as temporary:
        store, state = journal_start(Path(temporary))

        def fail(_store: SQLiteOperationalJournal, current: str) -> None:
            if current == point:
                raise RuntimeError("synthetic fault")

        with (
            patch.object(SQLiteOperationalJournal, "_checkpoint", fail),
            pytest.raises((RuntimeError, PersistenceError)),
        ):
            store.commit_operational_transition(state.scope, 0, funded_plan(state))
        recovered = SQLiteOperationalJournal.open(store.policy).load_operational_state(state.scope)
        if point == "after_commit":
            assert recovered.revision == 1
            assert len(recovered.book.inventory_book.funded_buy_book.reservations) == 1
        else:
            assert recovered == state
        assert_conserved(recovered)


class PersistedSellMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        count("initialized")
        self.temporary = tempfile.TemporaryDirectory(prefix="a17-3-machine-")
        self.store, self.state = durable_sell(Path(self.temporary.name))
        self.source = wire_scenario()
        self.original_reservation = self.state.book.inventory_book.reservations[0]
        self.other_bought = False
        self.staged_revision = self.state.revision
        self.raw_count = 0

    @rule()
    def load_and_stage(self) -> None:
        count("load_stage")
        self.staged_revision = self.store.load_operational_state(self.state.scope).revision

    @precondition(
        lambda self: self.state.book.sell_attempts[0].status is SellAttemptStatus.PREPARED
    )
    @rule()
    def uncertain(self) -> None:
        count("uncertain")
        self.state = self.store.commit_operational_transition(
            self.state.scope, self.state.revision, MarkOperationalSellUncertain(ref())
        )

    @precondition(
        lambda self: (
            self.state.book.sell_attempts[0].status is not SellAttemptStatus.EXECUTION_BOUND
        )
    )
    @rule()
    def bind_internal(self) -> None:
        count("bind_internal")
        self.state = self.store.commit_operational_transition(
            self.state.scope,
            self.state.revision,
            BindOperationalSell(ref(), context(self.state.book)),
        )

    @precondition(
        lambda self: self.state.book.sell_attempts[0].status is SellAttemptStatus.EXECUTION_BOUND
    )
    @rule()
    def bind_external(self) -> None:
        count("bind_external")
        self.state = self.store.commit_operational_transition(
            self.state.scope,
            self.state.revision,
            BindOperationalExternalSell(ref(), binding(self.state.book)),
        )

    @rule(index=st.integers(0, 2), conflict=st.booleans())
    def append(self, index: int, conflict: bool) -> None:
        count("append")
        raw = self.source.tape.observations[index]
        if conflict:
            raw = replace(raw, payload="{")
        self.state = self.store.append_raw_observation(self.state.scope, self.state.revision, raw)
        self.raw_count += 1

    @rule()
    def replay(self) -> None:
        count("replay")
        self.state = self.store.record_replay(
            self.state.scope, self.state.revision, self.source.plan
        )

    @rule()
    def staged_cas(self) -> None:
        count("staged_cas")
        raw = self.source.tape.observations[0]
        old = self.state
        if self.staged_revision != self.state.revision:
            with pytest.raises(PersistenceError) as error:
                self.store.append_raw_observation(self.state.scope, self.staged_revision, raw)
            assert error.value.code is PersistenceErrorCode.REVISION_CONFLICT
            assert self.store.load_operational_state(self.state.scope) == old
        else:
            self.state = self.store.append_raw_observation(
                self.state.scope, self.staged_revision, raw
            )
            self.raw_count += 1

    @rule()
    def rollback(self) -> None:
        count("rollback")

        def fail(_store: SQLiteOperationalJournal, point: str) -> None:
            if point == "after_event":
                raise RuntimeError("synthetic rollback")

        before = self.store.recover(self.state.scope)
        with (
            patch.object(SQLiteOperationalJournal, "_checkpoint", fail),
            pytest.raises(RuntimeError),
        ):
            self.store.append_raw_observation(
                self.state.scope, self.state.revision, self.source.tape.observations[0]
            )
        assert self.store.recover(self.state.scope) == before

    @rule()
    def restart(self) -> None:
        count("restart")
        self.store = SQLiteOperationalJournal.open(self.store.policy)
        assert self.store.load_operational_state(self.state.scope) == self.state

    @precondition(lambda self: not self.other_bought)
    @rule()
    def another_buy_without_touching_sell(self) -> None:
        count("other_buy")
        command = replace(funded_plan(self.state), cycle_ref=ref(1))
        self.state = self.store.commit_operational_transition(
            self.state.scope, self.state.revision, command
        )
        attempt = self.state.book.inventory_book.funded_buy_book.lifecycle.attempt_for(ref(1))
        assert attempt is not None
        ctx = BuyExecutionContext(attempt.intent, BuyExecutionRef("buy-1"))
        self.state = self.store.commit_operational_transition(
            self.state.scope, self.state.revision, BindOperationalBuy(ref(1), ctx)
        )
        finalized = finish(self.state.book.inventory_book.funded_buy_book, cell=1)
        self.state = self.store.commit_operational_transition(
            self.state.scope, self.state.revision, SettleOperationalBuy(finalized)
        )
        self.other_bought = True

    @rule()
    def corruption_detection_in_isolated_copy(self) -> None:
        count("corruption")
        with tempfile.TemporaryDirectory(prefix="a17-3-corrupt-") as directory:
            policy = JournalPathPolicy(Path(directory))
            shutil.copyfile(self.store.policy.database_path(), policy.database_path())
            with closing(sqlite3.connect(policy.database_path(), autocommit=True)) as connection:
                connection.execute("PRAGMA user_version=999")
            with pytest.raises(PersistenceError) as error:
                SQLiteOperationalJournal.open(policy)
            assert error.value.code is PersistenceErrorCode.UNKNOWN_SCHEMA

    @invariant()
    def conserved_authority_and_receipts(self) -> None:
        count("invariant")
        recovered = self.store.recover(self.state.scope)
        assert recovered.state == self.state
        assert (
            recovered.state.book.inventory_book.reservation_for(ref()) == self.original_reservation
        )
        assert len(recovered.receipts) == self.raw_count
        assert_conserved(recovered.state)

    def teardown(self) -> None:
        self.temporary.cleanup()


TestPersistedSellMachine = PersistedSellMachine.TestCase
TestPersistedSellMachine.settings = settings(
    max_examples=20, stateful_step_count=12, deadline=None, derandomize=True
)
