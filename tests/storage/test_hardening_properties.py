"""Oráculos externos: conservação, cobertura finita e restauração com anchors."""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import replace
from decimal import Decimal, localcontext
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from gridbot.application.operational_persistence import PersistenceError
from gridbot.domain import USDT, Money
from gridbot.storage.financial_codec import decode_contract, encode_contract
from gridbot.storage.journal_backup import create_verified_backup, restore_verified_backup
from gridbot.storage.operational_journal import SQLiteOperationalJournal
from tests.application.test_offline_sell_evidence import wire_scenario
from tests.storage.journal_oracle import audit_assets, audit_observed, audit_rows
from tests.storage.test_journal_backup import destination
from tests.storage.test_operational_journal import bound_sell

COUNTS: dict[str, int] = {}
FINITE = settings(max_examples=30, deadline=None, derandomize=True)


def count(name: str) -> None:
    COUNTS[name] = COUNTS.get(name, 0) + 1


@pytest.fixture(scope="module", autouse=True)
def actual_examples() -> object:
    yield
    sys.stdout.write("\nA17_4_ACTUAL_EXAMPLES=" + json.dumps(COUNTS, sort_keys=True) + "\n")


@FINITE
@given(st.integers(0, 10**60), st.integers(-128, 128), st.integers(2, 10))
def test_decimal_exact_under_hostile_context(
    coefficient: int, exponent: int, precision: int
) -> None:
    count("decimal_valid")
    original = Decimal((0, tuple(int(c) for c in str(coefficient)), exponent))
    with localcontext() as context:
        context.prec = precision
        decoded = decode_contract(encode_contract(Money(original, USDT)))
        assert type(decoded) is Money
        assert decoded.amount.as_tuple() == original.as_tuple()
        assert not any(context.flags.values())


@FINITE
@given(st.integers(97, 120))
def test_depth_limit_is_typed(depth: int) -> None:
    count("depth_invalid")
    node: object = None
    for _ in range(depth):
        node = {"tuple": [node]}
    with pytest.raises(PersistenceError):
        decode_contract(json.dumps({"schema": 1, "value": node}))
    count("depth_rejected")


@settings(max_examples=12, deadline=None, derandomize=True)
@given(st.permutations((0, 1, 2)), st.integers(0, 2), st.booleans())
def test_observation_order_and_conflict_keep_financial_authority(
    permutation: list[int], duplicate: int, conflict: bool
) -> None:
    count("observation_valid")
    with tempfile.TemporaryDirectory(prefix="a17-4-property-") as temporary:
        store, state = bound_sell(Path(temporary))
        original = state.book
        source = wire_scenario()
        items = tuple(source.tape.observations[i] for i in permutation)
        last = source.tape.observations[duplicate]
        if conflict:
            last = replace(last, payload="[]")
        state = store.append_raw_observations(state.scope, state.revision, (*items, last))
        state = store.record_replay(state.scope, state.revision, source.plan)
        recovered = SQLiteOperationalJournal.open(store.policy).recover(state.scope)
        assert recovered.state == state
        assert state.book == original
        audit_rows(store.policy.database_path(), expected_receipts=4)
        audit_assets(state)
        audit_observed(store.replay_observations(state.scope, source.plan))


class JournalHardeningMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        count("state_sequence")
        self.temporary = tempfile.TemporaryDirectory(prefix="a17-4-machine-")
        self.directory = Path(self.temporary.name)
        self.origin = destination(self.directory, "origin")
        self.store, self.state = bound_sell(self.origin.directory)
        self.financial = self.state.book
        self.source = wire_scenario()
        self.receipts = 0
        self.backups = 0

    @rule(index=st.integers(0, 2), conflict=st.booleans())
    def capture(self, index: int, conflict: bool) -> None:
        count("state_capture")
        raw = self.source.tape.observations[index]
        if conflict:
            raw = replace(raw, payload="[]")
        self.state = self.store.append_raw_observation(self.state.scope, self.state.revision, raw)
        self.receipts += 1

    @rule()
    def restart(self) -> None:
        count("state_restart")
        self.store = SQLiteOperationalJournal.open(self.origin)
        assert self.store.load_operational_state(self.state.scope) == self.state

    @rule()
    def replay(self) -> None:
        count("state_replay")
        self.state = self.store.record_replay(
            self.state.scope, self.state.revision, self.source.plan
        )
        audit_observed(self.store.replay_observations(self.state.scope, self.source.plan))

    @rule()
    def isolated_restore(self) -> None:
        count("state_restore")
        backup = destination(self.directory, f"backup-{self.backups}")
        restored = destination(self.directory, f"restored-{self.backups}")
        captured = create_verified_backup(self.store, backup)
        restore_verified_backup(backup, restored, expected_anchors=captured.anchors)
        assert SQLiteOperationalJournal.open(restored).recover(
            self.state.scope
        ) == self.store.recover(self.state.scope)
        self.backups += 1

    @invariant()
    def independent_authority(self) -> None:
        count("state_invariant")
        assert self.state.book == self.financial
        audit_assets(self.state)
        audit_rows(self.origin.database_path(), expected_receipts=self.receipts)

    def teardown(self) -> None:
        self.temporary.cleanup()


TestJournalHardeningMachine = JournalHardeningMachine.TestCase
TestJournalHardeningMachine.settings = settings(
    max_examples=10, stateful_step_count=8, deadline=None, derandomize=True
)
