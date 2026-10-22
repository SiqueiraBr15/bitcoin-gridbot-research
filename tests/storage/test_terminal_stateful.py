"""Máquina finita: revisão, duplicatas, captura completa e restart sem consumo."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import settings
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from gridbot.application.operational_persistence import PersistenceError, PersistenceErrorCode
from gridbot.application.sell_evidence import SellEvidenceError
from gridbot.application.sell_terminal import (
    ReconciledSellEvidence,
    validate_terminal_reconciliation_against_current,
)
from gridbot.exchange.binance.offline_evidence import RawSellObservation
from gridbot.storage.operational_journal import SQLiteOperationalJournal
from tests.application.test_offline_sell_evidence import edited, wire_scenario
from tests.storage.test_operational_journal import bound_sell

COUNTS: dict[str, int] = {}


def count(name: str) -> None:
    COUNTS[name] = COUNTS.get(name, 0) + 1


class TerminalJournalMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        count("machines")
        self.directory = TemporaryDirectory(prefix="gridbot-terminal-machine-")
        self.store, self.state = bound_sell(Path(self.directory.name))
        self.source = wire_scenario()
        self.plan = self.source.plan
        self.state = self.store.append_raw_observations(
            self.state.scope, self.state.revision, self.source.tape.observations
        )
        self.original_book = self.state.book
        self.pending = False
        self.counter = 0

    def teardown(self) -> None:
        self.directory.cleanup()

    @rule()
    def duplicate(self) -> None:
        count("duplicate")
        self._append((self.source.tape.observations[-1],))

    @rule()
    def incomplete_late_capture(self) -> None:
        count("late")
        self.counter += 1
        missing = edited(self.source, "page-0", "commission", None, remove=True)
        self._append(
            (
                replace(
                    missing.tape.observations[1],
                    source_ref=f"late-{self.counter}",
                    collection_ref=f"late-capture-{self.counter}",
                ),
            )
        )
        self.pending = True

    @rule()
    def fresh_complete_capture(self) -> None:
        count("refresh")
        self.counter += 1
        prefix = f"fresh-{self.counter}-"
        capture = f"machine-capture-{self.counter}"
        raws = tuple(
            replace(raw, source_ref=prefix + raw.source_ref, collection_ref=capture)
            for raw in self.source.tape.observations
        )
        self._append(raws)
        self.plan = replace(
            self.source.plan,
            query=replace(self.source.plan.query, collection_ref=capture),
            report_ref=prefix + "order",
            before_ref=prefix + "order",
            after_ref=prefix + "order",
            page_refs=(prefix + "page-0", prefix + "page-1"),
        )
        self.pending = False

    @rule()
    def restart(self) -> None:
        count("restart")
        before = self.store.reconcile_sell_terminal(
            self.state.scope, self.state.revision, self.plan
        )
        self.store = SQLiteOperationalJournal.open(self.store.policy)
        assert self.store.load_operational_state(self.state.scope) == self.state
        assert (
            self.store.reconcile_sell_terminal(self.state.scope, self.state.revision, self.plan)
            == before
        )

    def _append(self, raws: tuple[RawSellObservation, ...]) -> None:
        previous = self.store.reconcile_sell_terminal(
            self.state.scope, self.state.revision, self.plan
        )
        revision = self.state.revision
        self.state = self.store.append_raw_observations(self.state.scope, revision, raws)
        with pytest.raises(PersistenceError) as error:
            self.store.reconcile_sell_terminal(self.state.scope, revision, self.plan)
        assert error.value.code is PersistenceErrorCode.REVISION_CONFLICT
        current = self.store.reconcile_sell_terminal(
            self.state.scope, self.state.revision, self.plan
        )
        with pytest.raises(SellEvidenceError):
            validate_terminal_reconciliation_against_current(
                previous, self.state.book, current.journal_reference
            )
        assert self.state.book == self.original_book

    @invariant()
    def conclusion_is_current_and_has_no_financial_effect(self) -> None:
        count("invariant")
        result = self.store.reconcile_sell_terminal(
            self.state.scope, self.state.revision, self.plan
        )
        assert self.store.load_operational_state(self.state.scope).book == self.original_book
        if self.pending:
            assert result.evidence is None
        else:
            assert isinstance(result.evidence, ReconciledSellEvidence)
            assert result.evidence.executed_qty.value == Decimal(".031")


@pytest.fixture(scope="module", autouse=True)
def actual_sequences() -> Iterator[None]:
    yield
    sys.stdout.write("\nA17_5_STATE_COUNTS=" + json.dumps(COUNTS, sort_keys=True) + "\n")


TestTerminalJournalMachine = TerminalJournalMachine.TestCase
TestTerminalJournalMachine.settings = settings(
    max_examples=6, stateful_step_count=8, deadline=None, derandomize=True
)
