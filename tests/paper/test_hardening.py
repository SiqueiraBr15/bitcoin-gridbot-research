"""Durable economics and corruption regressions; real validators, bounded histories."""

import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

import gridbot.storage.paper_journal as implementation
from gridbot.domain import BTC, USDT, Asset, Money, OrderStatus, Qty
from gridbot.paper.accounting import (
    PaperAccount,
    PaperApplySell,
    PaperBook,
    PaperError,
    PaperErrorCode,
    PaperObserveSell,
    PaperPrepareBuy,
    PaperReleaseNoFill,
    PaperSettleBuy,
    paper_transition,
)
from gridbot.portfolio import BuyExecutionRef
from gridbot.storage.paper_codec import decode_initial, encode_command
from gridbot.storage.paper_journal import PaperJournal, PaperPersistenceCode, PaperPersistenceError
from tests.paper.fixtures import buy_result, commit, evidence, prepare_buy, reserve_sell
from tests.paper.hardening_fixtures import raw_oracle, seeded_history
from tests.paper.test_journal import persisted
from tests.paper.test_realistic_cycle import realistic_initial


@pytest.mark.parametrize("count", [0, 1, 64, 255, 256])
def test_real_history_capacity_recovers_every_event(tmp_path: Path, count: int) -> None:
    store = seeded_history(tmp_path, count)
    book = store.recover()
    assert len(book.entries) == count
    assert book.revision == count
    assert book.settled_sell_proceeds == Money.zero(USDT)
    if count >= 3:
        assert book.grid_state.cells[0].cycle_seq == 0
        assert book.reserved_grid_base > Qty.zero()


@pytest.mark.parametrize("count", [257, 512, 1000])
def test_over_capacity_history_is_rejected_whole_without_prefix_credit(
    tmp_path: Path, count: int
) -> None:
    store = seeded_history(tmp_path, count)
    path = tmp_path / "gridbot-paper.sqlite3"
    before = path.read_bytes()
    with pytest.raises(PaperPersistenceError) as error:
        store.recover()
    assert error.value.code is PaperPersistenceCode.CORRUPT_DATABASE
    assert path.read_bytes() == before


def test_last_slot_and_next_append_are_atomic_and_typed(tmp_path: Path) -> None:
    store = seeded_history(tmp_path, 255)
    before = store.recover()
    command = before.entries[-1]
    accepted = store.commit(255, command)
    assert len(accepted.entries) == 256
    path = tmp_path / "gridbot-paper.sqlite3"
    full_bytes = path.read_bytes()
    with pytest.raises(PaperPersistenceError) as error:
        store.commit(256, command)
    assert error.value.code is PaperPersistenceCode.CAPACITY_EXCEEDED
    assert path.read_bytes() == full_bytes
    recovered = store.recover()
    assert recovered == accepted
    assert recovered.settled_sell_proceeds == Money.zero(USDT)


def test_byte_budget_rejection_does_not_corrupt_existing_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, book, _execution, source = persisted(tmp_path)
    command = PaperObserveSell(source)
    path = tmp_path / "gridbot-paper.sqlite3"
    before = path.read_bytes()
    with closing(sqlite3.connect(path)) as connection:
        size = connection.execute(
            "SELECT length(CAST(initial AS BLOB)) + "
            "(SELECT SUM(length(CAST(payload AS BLOB))) FROM paper_events) FROM paper_meta"
        ).fetchone()[0]
    payload_size = len(encode_command(command).encode("utf8"))
    monkeypatch.setattr(implementation, "MAX_HISTORY_BYTES", size + payload_size - 1)
    with pytest.raises(PaperPersistenceError) as error:
        store.commit(book.revision, command)
    assert error.value.code is PaperPersistenceCode.CAPACITY_EXCEEDED
    assert path.read_bytes() == before
    assert store.recover() == book


def test_existing_unescaped_unicode_initial_counts_bytes_during_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = realistic_initial()
    book = PaperBook(replace(original.initial, account=PaperAccount("PAPER:é")))
    store = PaperJournal.create(tmp_path, book)
    path = tmp_path / "gridbot-paper.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        encoded = connection.execute("SELECT initial FROM paper_meta").fetchone()[0]
        outer = json.loads(encoded)
        outer["payload"] = json.dumps(json.loads(outer["payload"]), ensure_ascii=False)
        unescaped = json.dumps(outer, ensure_ascii=False)
        connection.execute("DROP TRIGGER paper_meta_no_update")
        connection.execute(
            "UPDATE paper_meta SET initial=?, digest=?",
            (
                unescaped,
                hashlib.sha256(unescaped.encode("utf8")).hexdigest(),
            ),
        )
        connection.execute(implementation.TABLES[2])
    assert decode_initial(unescaped) == book.initial
    prepared = prepare_buy(original, budget="20").entries[0]
    assert isinstance(prepared, PaperPrepareBuy)
    command = replace(prepared, execution_ref=BuyExecutionRef("PAPER:é:BUY:1"))
    assert len(paper_transition(book, 0, command).entries) == 1
    required = len(unescaped.encode("utf8")) + len(encode_command(command).encode("utf8"))
    monkeypatch.setattr(implementation, "MAX_HISTORY_BYTES", required - 1)
    before = path.read_bytes()
    with pytest.raises(PaperPersistenceError) as error:
        store.commit(0, command)
    assert error.value.code is PaperPersistenceCode.CAPACITY_EXCEEDED
    assert path.read_bytes() == before
    assert store.recover() == book


def test_durable_twenty_usdt_second_buy_only_after_recorded_settlement(tmp_path: Path) -> None:
    book = realistic_initial()
    store = PaperJournal.create(tmp_path, book)

    def save(candidate: PaperBook) -> dict[str, Fraction]:
        nonlocal book, store
        assert len(candidate.entries) == len(book.entries) + 1
        updated = store.commit(len(book.entries), candidate.entries[-1])
        store = PaperJournal.open(tmp_path)
        book = store.recover()
        assert book == candidate == updated
        return raw_oracle(book)

    for cell in (0, 1, 2):
        save(prepare_buy(book, cell, budget="20"))
    save(commit(book, PaperSettleBuy(buy_result(book, fee=".000000102"))))
    available_before = book.available_quote
    candidate, execution = reserve_sell(book, hold=".0000001")
    save(candidate)
    source = evidence(
        book, execution, execution_price="65500", fees=(Money.parse(".0066155", USDT),)
    )
    save(commit(book, PaperObserveSell(source)))
    assert book.available_quote == available_before == Money.parse(".0288", USDT)
    with pytest.raises(PaperError) as error:
        prepare_buy(book, budget="19.8")
    # This cell still belongs to its first SELL cycle; its BUY identity cannot be reused.
    assert error.value.code is PaperErrorCode.IDENTITY_CONFLICT
    settlement = PaperApplySell(execution, len(book.entries))
    applied = save(commit(book, settlement))
    assert applied["available"] == Fraction("6.6376845")
    save(prepare_buy(book, budget="19.8"))
    final = save(commit(book, PaperSettleBuy(buy_result(book, fee=".000000101"))))
    assert final["available"] == Fraction(".0726845")
    assert final["btc"] == Fraction(".000101797")
    assert store.commit(len(book.entries), settlement) == book
    assert store.recover() == book


@pytest.mark.parametrize("outcome", ["partial", "no-fill", "unknown", "late-fee"])
def test_restart_outcomes_and_late_conflict_cannot_double_apply(
    tmp_path: Path, outcome: str
) -> None:
    store, book, execution, source = persisted(tmp_path)
    if outcome == "partial":
        source = evidence(
            book,
            execution,
            status=OrderStatus.CANCELED,
            qty=".030",
            fees=(
                Money.parse(".00004", BTC),
                Money.parse(".00105", USDT),
                Money.parse(".00001", Asset("BNB")),
            ),
        )
    elif outcome == "no-fill":
        source = evidence(book, execution, status=OrderStatus.CANCELED, qty="0")
    elif outcome == "unknown":
        source = evidence(book, execution, status=None)
    book = store.commit(book.revision, PaperObserveSell(source))
    restored = PaperJournal.open(tmp_path)
    old = book
    apply = PaperApplySell(execution, book.revision)
    if outcome == "unknown":
        with pytest.raises(PaperError) as error:
            restored.commit(book.revision, apply)
        assert error.value.code is PaperErrorCode.EVIDENCE_PENDING
        assert restored.recover() == old
        assert old.settled_sell_proceeds == Money.zero(USDT)
        return
    book = restored.commit(book.revision, apply)
    restored = PaperJournal.open(tmp_path)
    assert restored.commit(book.revision, apply) == book
    raw_oracle(book)
    if outcome == "partial":
        assert book.reserved_grid_base == Qty.parse(".00106")
        assert book.third_asset_obligations() == (Money.parse(".00001", Asset("BNB")),)
        assert book.grid_state.cells[0].cycle_seq == 0
    elif outcome == "no-fill":
        release = PaperReleaseNoFill(execution)
        book = restored.commit(book.revision, release)
        restored = PaperJournal.open(tmp_path)
        assert restored.commit(book.revision, release) == book
        assert book.reserved_grid_base.is_zero
        assert book.grid_state.cells[0].cycle_seq == 0
    else:
        changed = replace(
            source,
            reconciliation=evidence(
                old, execution, fees=(Money.parse(".02", USDT),)
            ).reconciliation,
        )
        book = restored.commit(book.revision, PaperObserveSell(changed))
        restored = PaperJournal.open(tmp_path)
        with pytest.raises(PaperError) as error:
            restored.commit(book.revision, PaperApplySell(execution, book.revision))
        assert error.value.code is PaperErrorCode.SETTLEMENT_CONFLICT
        assert book.incident_blocked
        with pytest.raises(PaperError) as old_selection:
            restored.commit(book.revision, apply)
        assert old_selection.value.code is PaperErrorCode.INCIDENT_BLOCKED
        assert restored.recover() == book
        assert book.settled_sell_proceeds == Money.parse("3.245", USDT)


@pytest.mark.parametrize("damage", ["digest", "missing", "rehashed-revision", "duplicate-apply"])
def test_corruption_with_original_schema_reaches_chain_and_economic_guards(
    tmp_path: Path, damage: str
) -> None:
    store, book, execution, source = persisted(tmp_path)
    book = store.commit(book.revision, PaperObserveSell(source))
    apply = PaperApplySell(execution, book.revision)
    book = store.commit(book.revision, apply)
    path = tmp_path / "gridbot-paper.sqlite3"
    before = path.read_bytes()
    target = tmp_path / "copy"
    target.mkdir()
    copied = target / path.name
    shutil.copyfile(path, copied)
    with closing(sqlite3.connect(copied)) as connection, connection:
        connection.execute("DROP TRIGGER paper_events_no_update")
        connection.execute("DROP TRIGGER paper_events_no_delete")
        if damage == "digest":
            connection.execute("UPDATE paper_events SET payload=payload || ' ' WHERE sequence=1")
        elif damage == "missing":
            connection.execute("DELETE FROM paper_events WHERE sequence=2")
        else:
            rows = connection.execute(
                "SELECT sequence,payload FROM paper_events ORDER BY sequence"
            ).fetchall()
            if damage == "duplicate-apply":
                rows.append((6, encode_command(apply)))
            else:
                rows[-1] = (5, encode_command(PaperApplySell(execution, 3)))
            previous = connection.execute("SELECT digest FROM paper_meta").fetchone()[0]
            for sequence, payload in rows:
                digest = hashlib.sha256(f"{sequence}\n{previous}\n{payload}".encode()).hexdigest()
                connection.execute(
                    "INSERT OR REPLACE INTO paper_events VALUES(?,?,?,?)",
                    (sequence, payload, previous, digest),
                )
                previous = digest
        connection.execute(implementation.TABLES[4])
        connection.execute(implementation.TABLES[5])
    with pytest.raises(PaperPersistenceError) as error:
        PaperJournal.open(target)
    assert error.value.code is PaperPersistenceCode.CORRUPT_DATABASE
    assert path.read_bytes() == before
