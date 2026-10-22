"""Round-trip completo, autoridade, evidências e falhas locais sem efeito SELL."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import FrozenInstanceError, fields, replace
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Any, cast

import pytest

from gridbot.application import (
    BuyLifecycleBook,
    FundedBuyBook,
    GridOperationalBook,
    SellInventoryBook,
)
from gridbot.application.operational_persistence import (
    BindOperationalBuy,
    BindOperationalExternalSell,
    BindOperationalSell,
    MarkOperationalBuyUncertain,
    MarkOperationalSellUncertain,
    OperationalScope,
    PersistenceError,
    PersistenceErrorCode,
    PrepareOperationalBuy,
    PrepareOperationalSell,
    ReserveOperationalSell,
    SettleOperationalBuy,
    VersionedOperationalState,
)
from gridbot.application.sell_intents import build_sell_intent_for_cell
from gridbot.application.sell_lifecycle import SellAttemptStatus
from gridbot.domain import BTC, USDT, DomainError, Money, Qty
from gridbot.portfolio.buy_finalization import BuyExecutionContext, BuyExecutionRef
from gridbot.storage.financial_codec import decode_contract, encode_contract, revalidate_contract
from gridbot.storage.journal_models import ReceiptClassification
from gridbot.storage.journal_paths import JournalPathPolicy
from gridbot.storage.operational_journal import SQLiteOperationalJournal
from gridbot.strategy import build_buy_intents, size_grid_buys
from tests.application.test_external_sell_identity import binding
from tests.application.test_offline_sell_evidence import edited, wire_scenario
from tests.application.test_operational_grid import context, prepared_root, ref, with_status
from tests.application.test_sell_inventory import assessment, finish, grid, rules

E = PersistenceErrorCode


def pristine() -> GridOperationalBook:
    return GridOperationalBook(
        SellInventoryBook(FundedBuyBook(BuyLifecycleBook(grid()), Money.parse("20", USDT)))
    )


def scope_for(book: GridOperationalBook, account: str = "synthetic-account") -> OperationalScope:
    return OperationalScope("BINANCE_SPOT", account, "synthetic", book.grid_state.plan.spec.symbol)


def journal_start(directory: Path) -> tuple[SQLiteOperationalJournal, VersionedOperationalState]:
    store = SQLiteOperationalJournal.create(JournalPathPolicy(directory))
    root = pristine()
    return store, store.initialize_scope(scope_for(root), root)


def funded_plan(state: VersionedOperationalState) -> PrepareOperationalBuy:
    grid_state = state.book.grid_state
    plan = build_buy_intents(
        grid_state, size_grid_buys(grid_state, rules(), Money.parse("10", USDT))
    )
    return PrepareOperationalBuy(plan, ref(), Money.parse("0.01", USDT))


def durable_sell(
    directory: Path, cells: tuple[int, ...] = (0,)
) -> tuple[SQLiteOperationalJournal, VersionedOperationalState]:
    store, state = journal_start(directory)
    prepare = funded_plan(state)
    for cell in cells:
        state = store.commit_operational_transition(
            state.scope, state.revision, replace(prepare, cycle_ref=ref(cell))
        )
        attempt = state.book.inventory_book.funded_buy_book.lifecycle.attempt_for(ref(cell))
        assert attempt is not None
        ctx = BuyExecutionContext(attempt.intent, BuyExecutionRef(f"buy-{cell}"))
        state = store.commit_operational_transition(
            state.scope, state.revision, BindOperationalBuy(ref(cell), ctx)
        )
    for cell in cells:
        finalized = finish(state.book.inventory_book.funded_buy_book, cell)
        state = store.commit_operational_transition(
            state.scope, state.revision, SettleOperationalBuy(finalized)
        )
        candidate = assessment(state.book.inventory_book, cell)
        state = store.commit_operational_transition(
            state.scope, state.revision, ReserveOperationalSell(candidate, Qty.parse("0.0001"))
        )
        plan = build_sell_intent_for_cell(state.book.inventory_book, ref(cell))
        state = store.commit_operational_transition(
            state.scope, state.revision, PrepareOperationalSell(plan, ref(cell))
        )
    return store, state


def bound_sell(directory: Path) -> tuple[SQLiteOperationalJournal, VersionedOperationalState]:
    store, state = durable_sell(directory)
    state = store.commit_operational_transition(
        state.scope, state.revision, BindOperationalSell(ref(), context(state.book))
    )
    state = store.commit_operational_transition(
        state.scope, state.revision, BindOperationalExternalSell(ref(), binding(state.book))
    )
    return store, state


def assert_conserved(state: VersionedOperationalState) -> None:
    inventory = state.book.inventory_book
    funded = inventory.funded_buy_book
    spent_oracle = sum(
        (
            Fraction(fill.execution_price.value) * Fraction(fill.executed_qty.value)
            + (Fraction(fill.fee.amount) if fill.fee.asset == USDT else 0)
            for finalized in funded.lifecycle.consumed
            for fill in finalized.ledger.fills
        ),
        Fraction(),
    )
    reserved_oracle = sum(
        (
            Fraction(reservation.intent.price.value) * Fraction(reservation.intent.qty.value)
            + Fraction(reservation.quote_fee_hold.amount)
            for reservation in funded.reservations
        ),
        Fraction(),
    )
    assert funded.initial_quote_capital.amount == Decimal("20")
    assert Fraction(funded.spent_quote.amount) == spent_oracle
    assert Fraction(funded.reserved_quote.amount) == reserved_oracle
    assert Fraction(funded.available_quote.amount) == Fraction(20) - spent_oracle - reserved_oracle
    assert Fraction(funded.initial_quote_capital.amount) == (
        Fraction(funded.spent_quote.amount)
        + Fraction(funded.reserved_quote.amount)
        + Fraction(funded.available_quote.amount)
    )
    for reservation in inventory.reservations:
        origin = reservation.finalized_buy.ledger
        net = sum(
            (
                Fraction(f.executed_qty.value)
                - (Fraction(f.fee.amount) if f.fee.asset == BTC else 0)
                for f in origin.fills
            ),
            Fraction(),
        )
        committed = Fraction(reservation.reserved_sell_qty.value) + Fraction(
            reservation.base_fee_hold.value
        )
        assert committed <= net
        assert net == committed + Fraction(reservation.unreserved_base_qty.value)
    assert all(c.cycle_seq == 0 for c in state.book.grid_state.cells)


@pytest.mark.parametrize("status", list(SellAttemptStatus))
def test_complete_graph_codec_preserves_historical_sources_and_uncertainty(
    status: SellAttemptStatus,
) -> None:
    root = with_status(prepared_root((0, 1, 2)), status, cell=1)
    checked = revalidate_contract(root, GridOperationalBook)
    assert checked == root
    assert encode_contract(checked) == encode_contract(root)
    assert checked.sell_attempts[1].status is status
    assert checked.inventory_book.reservations == root.inventory_book.reservations
    assert checked.inventory_book.funded_buy_book.lifecycle.consumed == (
        root.inventory_book.funded_buy_book.lifecycle.consumed
    )


@pytest.mark.parametrize("text", ["-0.0000", "0E-100", "1E-1000", "123.45000", "-123.45000"])
def test_decimal_tuple_survives_small_context_without_rounding(text: str) -> None:
    original = Money(Decimal(text), USDT)
    with localcontext() as ctx:
        ctx.prec = 2
        recovered = revalidate_contract(original, Money)
        assert recovered.amount.as_tuple() == original.amount.as_tuple()
        assert recovered.asset == original.asset
        assert not any(ctx.flags.values())


@pytest.mark.parametrize("unknown", [float("nan"), float("inf"), 0.1, {}, [], object()])
def test_codec_refuses_untyped_graph_and_float(unknown: object) -> None:
    with pytest.raises(PersistenceError):
        encode_contract(unknown)


@pytest.mark.parametrize(
    "payload",
    [
        "{",
        "null",
        '{"schema":1,"schema":1,"value":0}',
        '{"schema":1,"value":0.1}',
        '{"schema":1,"value":NaN}',
    ],
)
def test_codec_corrupt_json_never_invents_zero(payload: str) -> None:
    with pytest.raises(PersistenceError) as error:
        decode_contract(payload)
    assert error.value.code is E.CORRUPT_JSON


@pytest.mark.parametrize("kind", ["schema", "unknown-type", "missing-capital", "unknown-field"])
def test_known_schema_rejects_missing_or_external_classes(kind: str) -> None:
    payload = json.loads(encode_contract(pristine()))
    if kind == "schema":
        payload["schema"] = 999
    elif kind == "unknown-type":
        payload["value"]["type"] = "os.system"
    elif kind == "missing-capital":
        del payload["value"]["fields"]["inventory_book"]["fields"]["funded_buy_book"]["fields"][
            "initial_quote_capital"
        ]
    else:
        payload["value"]["fields"]["available_quote"] = "1000"
    with pytest.raises(PersistenceError):
        decode_contract(json.dumps(payload))


def test_restart_preserves_all_three_states_and_other_cells(tmp_path: Path) -> None:
    store, state = durable_sell(tmp_path, (0, 1, 2))
    state = store.commit_operational_transition(
        state.scope, state.revision, MarkOperationalSellUncertain(ref(1))
    )
    state = store.commit_operational_transition(
        state.scope, state.revision, BindOperationalSell(ref(2), context(state.book, 2))
    )
    state = store.commit_operational_transition(
        state.scope, state.revision, BindOperationalExternalSell(ref(2), binding(state.book, 2))
    )
    reopened = SQLiteOperationalJournal.open(store.policy)
    recovered = reopened.load_operational_state(state.scope)
    assert recovered == state
    assert [a.status for a in recovered.book.sell_attempts] == [
        SellAttemptStatus.PREPARED,
        SellAttemptStatus.SUBMISSION_UNCERTAIN,
        SellAttemptStatus.EXECUTION_BOUND,
    ]
    assert_conserved(recovered)


def test_durable_buy_uncertain_hold_and_consumption_are_unique(tmp_path: Path) -> None:
    store, state = journal_start(tmp_path)
    state = store.commit_operational_transition(state.scope, 0, funded_plan(state))
    held = state.book.inventory_book.funded_buy_book.reserved_quote
    state = store.commit_operational_transition(
        state.scope, state.revision, MarkOperationalBuyUncertain(ref())
    )
    state = SQLiteOperationalJournal.open(store.policy).load_operational_state(state.scope)
    assert state.book.inventory_book.funded_buy_book.reserved_quote == held
    attempt = state.book.inventory_book.funded_buy_book.lifecycle.attempt_for(ref())
    assert attempt is not None
    ctx = BuyExecutionContext(attempt.intent, BuyExecutionRef("buy-0"))
    state = store.commit_operational_transition(
        state.scope, state.revision, BindOperationalBuy(ref(), ctx)
    )
    finalized = finish(state.book.inventory_book.funded_buy_book)
    state = store.commit_operational_transition(
        state.scope, state.revision, SettleOperationalBuy(finalized)
    )
    repeated = store.commit_operational_transition(
        state.scope, state.revision, SettleOperationalBuy(finalized)
    )
    assert repeated.book == state.book
    assert repeated.revision == state.revision + 1
    assert_conserved(repeated)


def test_cas_rejects_stale_before_noop_and_preserves_authority(tmp_path: Path) -> None:
    store, state = journal_start(tmp_path)
    second = SQLiteOperationalJournal.open(store.policy)
    command = funded_plan(state)
    winner = store.commit_operational_transition(state.scope, 0, command)
    with pytest.raises(PersistenceError) as error:
        second.commit_operational_transition(state.scope, 0, command)
    assert error.value.code is E.REVISION_CONFLICT
    assert second.load_operational_state(state.scope) == winner


def test_snapshot_save_rewrap_and_import_of_past_are_blocked(tmp_path: Path) -> None:
    store, state = bound_sell(tmp_path)
    lost = GridOperationalBook(SellInventoryBook(state.book.inventory_book.funded_buy_book))
    with pytest.raises(PersistenceError):
        store.commit_operational_transition(state.scope, state.revision, cast(Any, lost))
    with pytest.raises(PersistenceError):
        store.initialize_scope(replace(state.scope, account_ref="another"), lost)
    assert store.load_operational_state(state.scope) == state
    assert not hasattr(store, "save")


def test_atomic_transition_and_raw_use_journal_sequence_not_receipt_count(tmp_path: Path) -> None:
    store, state = bound_sell(tmp_path)
    raw = wire_scenario().tape.observations[0]
    command = BindOperationalExternalSell(ref(), binding(state.book))
    updated = store.commit_operational_transition(
        state.scope, state.revision, command, evidence_entries=(raw, raw)
    )
    recovered = SQLiteOperationalJournal.open(store.policy).recover(state.scope)
    assert recovered.state == updated
    assert len(recovered.receipts) == 2
    assert recovered.receipts[1].sequence == recovered.receipts[0].sequence + 1
    assert recovered.receipts[1].classification is ReceiptClassification.DUPLICATE_IDENTICAL


def test_raw_durable_before_parse_and_quarantine_history_is_not_erased(tmp_path: Path) -> None:
    store, state = bound_sell(tmp_path)
    source = wire_scenario()
    invalid = edited(source, "page-0", "commission", None, remove=True)
    state = store.append_raw_observations(state.scope, state.revision, invalid.tape.observations)
    store = SQLiteOperationalJournal.open(store.policy)
    assert [r.raw for r in store.recover(state.scope).receipts] == list(invalid.tape.observations)
    state = store.record_replay(state.scope, state.revision, source.plan)
    after = SQLiteOperationalJournal.open(store.policy).recover(state.scope)
    assert after.replays[0].quarantined_sources
    assert after.replays[0].issues
    assert store.replay_observations(state.scope, source.plan).candidate is None
    assert state.book.inventory_book.funded_buy_book.available_quote.amount == Decimal("16.8")
    assert_conserved(after.state)


def test_identical_and_conflicting_raw_survive_restart(tmp_path: Path) -> None:
    store, state = bound_sell(tmp_path)
    source = wire_scenario()
    state = store.append_raw_observations(state.scope, state.revision, source.tape.observations)
    raw = source.tape.observations[1]
    state = store.append_raw_observation(state.scope, state.revision, raw)
    assert store.replay_observations(state.scope, source.plan).candidate is not None
    conflict = replace(raw, payload="[]")
    state = store.append_raw_observation(state.scope, state.revision, conflict)
    recovered = SQLiteOperationalJournal.open(store.policy).recover(state.scope)
    assert len(recovered.receipts) == 5
    assert recovered.receipts[-2].classification is ReceiptClassification.DUPLICATE_IDENTICAL
    assert recovered.receipts[-1].classification is ReceiptClassification.DUPLICATE_CONFLICTING
    assert recovered.receipts[1].raw == raw
    assert store.replay_observations(state.scope, source.plan).candidate is None


def test_foreign_account_raw_is_preserved_without_contaminating_replay(tmp_path: Path) -> None:
    store, state = bound_sell(tmp_path)
    source = wire_scenario()
    raw = source.tape.observations[1]
    foreign = replace(raw, scope=replace(raw.scope, account_ref="foreign"), payload="{")
    state = store.append_raw_observations(
        state.scope, state.revision, (*source.tape.observations, foreign)
    )
    recovered = SQLiteOperationalJournal.open(store.policy).recover(state.scope)
    assert recovered.receipts[-1].classification is ReceiptClassification.FOREIGN_SCOPE
    assert recovered.receipts[-1].raw.payload == "{"
    assert store.replay_observations(state.scope, source.plan).candidate is not None
    with pytest.raises(PersistenceError):
        store.replay_observations(
            state.scope,
            replace(
                source.plan,
                query=replace(
                    source.plan.query,
                    identity=replace(source.plan.query.identity, account_ref="foreign"),
                ),
            ),
        )


def test_namespaces_are_distinct_and_one_authority_per_scope(tmp_path: Path) -> None:
    store, state = journal_start(tmp_path)
    foreign = replace(state.scope, account_ref="other")
    another = store.initialize_scope(foreign, pristine())
    state = store.commit_operational_transition(state.scope, 0, funded_plan(state))
    assert store.load_operational_state(foreign) == another
    with pytest.raises(PersistenceError) as error:
        store.initialize_scope(state.scope, pristine())
    assert error.value.code is E.DUPLICATE_SCOPE


def test_append_only_sql_triggers_and_no_public_delete(tmp_path: Path) -> None:
    store, state = journal_start(tmp_path)
    with closing(sqlite3.connect(store.policy.database_path(), autocommit=True)) as connection:
        for statement in (
            "DELETE FROM entries",
            "DELETE FROM revisions",
            "DELETE FROM states",
            "DELETE FROM meta",
            "DELETE FROM heads",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(statement)
    assert store.load_operational_state(state.scope) == state


def test_missing_empty_and_unknown_schema_fail_closed(tmp_path: Path) -> None:
    policy = JournalPathPolicy(tmp_path)
    with pytest.raises(PersistenceError) as missing:
        SQLiteOperationalJournal.open(policy)
    assert missing.value.code is E.NOT_FOUND
    path = policy.database_path()
    path.touch()
    with pytest.raises(PersistenceError) as empty:
        SQLiteOperationalJournal.open(policy)
    assert empty.value.code is E.EMPTY_DATABASE
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA user_version=999")
    with pytest.raises(PersistenceError) as unknown:
        SQLiteOperationalJournal.open(policy)
    assert unknown.value.code is E.UNKNOWN_SCHEMA


def test_records_frozen_and_no_financial_total_cache(tmp_path: Path) -> None:
    store, state = bound_sell(tmp_path)
    for obj in (state, state.scope, store, store.policy):
        with pytest.raises(FrozenInstanceError):
            cast(Any, obj).unexpected = 1
    assert {f.name for f in fields(VersionedOperationalState)} == {"scope", "revision", "book"}


def test_known_sensitive_input_is_rejected_without_echoing_or_graving(tmp_path: Path) -> None:
    store, state = bound_sell(tmp_path)
    raw = replace(
        wire_scenario().tape.observations[0], payload='{"api_key":"synthetic-placeholder"}'
    )
    with pytest.raises(PersistenceError) as error:
        store.append_raw_observation(state.scope, state.revision, raw)
    assert error.value.code is E.SENSITIVE_INPUT
    assert "synthetic-placeholder" not in str(error.value)
    assert store.recover(state.scope).receipts == ()
    assert store.load_operational_state(state.scope) == state


def test_failed_financial_validation_rolls_back_state_and_related_raw(tmp_path: Path) -> None:
    store, state = journal_start(tmp_path)
    command = replace(funded_plan(state), quote_fee_hold=Money.parse("100", USDT))
    with pytest.raises(DomainError):
        store.commit_operational_transition(
            state.scope, 0, command, evidence_entries=wire_scenario().tape.observations
        )
    assert store.load_operational_state(state.scope) == state
    assert store.recover(state.scope).receipts == ()
