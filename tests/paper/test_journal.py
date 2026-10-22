import shutil
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

import gridbot.storage.paper_journal as implementation
from gridbot.domain import USDT, DomainError, Money, OrderStatus
from gridbot.paper.accounting import PaperApplySell, PaperObserveSell, PaperReleaseNoFill
from gridbot.storage.financial_codec import encode_contract
from gridbot.storage.journal_paths import JournalPathPolicy
from gridbot.storage.operational_journal import SQLiteOperationalJournal
from gridbot.storage.paper_codec import decode_command, encode_command, encode_initial
from gridbot.storage.paper_journal import PaperJournal, PaperPersistenceCode, PaperPersistenceError
from tests.paper.fixtures import bought, commit, evidence, initial, reserve_sell
from tests.paper.test_accounting import conservation
from tests.storage.test_operational_journal import bound_sell


def persisted(tmp_path: Path) -> tuple[PaperJournal, Any, Any, Any]:
    original = initial()
    book, execution = reserve_sell(bought(original))
    store = PaperJournal.create(tmp_path, original)
    current = original
    for event in book.entries:
        current = store.commit(current.revision, event)
    return store, current, execution, evidence(current, execution)


@pytest.mark.parametrize(
    ("qty", "status"),
    [(None, OrderStatus.FILLED), (".015", OrderStatus.CANCELED), ("0", OrderStatus.CANCELED)],
)
def test_recovery_residual_proceeds_and_unique_settlement(
    tmp_path: Path, qty: str | None, status: OrderStatus
) -> None:
    store, book, execution, _ = persisted(tmp_path)
    source = evidence(book, execution, qty=qty, status=status)
    book = store.commit(book.revision, PaperObserveSell(source))
    apply = PaperApplySell(execution, book.revision)
    final = store.commit(book.revision, apply)
    restored = PaperJournal.open(tmp_path)
    assert restored.recover() == final
    assert restored.commit(final.revision, apply) == final
    conservation(final)
    if qty == "0":
        final = restored.commit(final.revision, PaperReleaseNoFill(execution))
        assert PaperJournal.open(tmp_path).recover() == final
        assert final.reserved_grid_base.is_zero


@pytest.mark.parametrize("boundary", ["before", "after", "commit_then_error", "close"])
def test_atomicity_and_commit_uncertainty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    store, book, execution, source = persisted(tmp_path)
    book = store.commit(book.revision, PaperObserveSell(source))
    command = PaperApplySell(execution, book.revision)
    expected = commit(book, command)

    def fault(connection: sqlite3.Connection) -> None:
        if boundary == "commit_then_error":
            connection.execute("COMMIT")
        if boundary == "close":
            connection.close()
        raise OSError("synthetic PAPER boundary fault")

    names = {
        "before": "_before_commit",
        "after": "_after_commit",
        "commit_then_error": "_commit",
        "close": "_close",
    }
    with monkeypatch.context() as context:
        context.setattr(implementation, names[boundary], fault)
        with pytest.raises((OSError, PaperPersistenceError)) as error:
            store.commit(book.revision, command)
        if boundary != "before":
            assert isinstance(error.value, PaperPersistenceError)
            assert error.value.code is PaperPersistenceCode.COMMIT_UNCERTAIN
    actual = PaperJournal.open(tmp_path).recover()
    assert actual == (book if boundary == "before" else expected)
    if boundary != "before":
        assert store.commit(actual.revision, command) == actual


def test_cas_two_instances_and_failed_apply_without_mutation(tmp_path: Path) -> None:
    store, book, execution, source = persisted(tmp_path)
    other = PaperJournal.open(tmp_path)
    new = store.commit(book.revision, PaperObserveSell(source))
    with pytest.raises(DomainError):
        other.commit(book.revision, PaperObserveSell(source))
    before = (tmp_path / "gridbot-paper.sqlite3").read_bytes()
    with pytest.raises(DomainError):
        other.commit(new.revision, PaperApplySell(execution, 0))
    assert other.recover() == new
    assert (tmp_path / "gridbot-paper.sqlite3").read_bytes() == before


def test_no_production_codec_or_journal_promotion(tmp_path: Path) -> None:
    book = initial()
    with pytest.raises(DomainError):
        encode_contract(book)
    with pytest.raises(DomainError):
        PaperJournal.create(tmp_path, cast(Any, object()))
    store = PaperJournal.create(tmp_path, book)
    shutil.copyfile(tmp_path / "gridbot-paper.sqlite3", tmp_path / "gridbot-state.sqlite3")
    with pytest.raises(DomainError):
        SQLiteOperationalJournal.open(JournalPathPolicy(tmp_path))
    with pytest.raises(DomainError):
        store.recover()


def test_foreign_production_database_not_changed_by_paper_open(tmp_path: Path) -> None:
    original_dir = tmp_path / "production"
    original_dir.mkdir()
    source, _state = bound_sell(original_dir)
    target = tmp_path / "paper"
    target.mkdir()
    production = source.policy.database_path()
    copied = target / "gridbot-paper.sqlite3"
    shutil.copyfile(production, copied)
    before = copied.read_bytes()
    with pytest.raises(PaperPersistenceError) as error:
        PaperJournal.open(target)
    assert error.value.code is PaperPersistenceCode.FOREIGN_DATABASE
    assert copied.read_bytes() == before
    assert production.read_bytes() == before


def test_corrupt_history_and_json_duplicate_rejected(tmp_path: Path) -> None:
    store, book, _execution, source = persisted(tmp_path)
    store.commit(book.revision, PaperObserveSell(source))
    command = encode_command(PaperObserveSell(source))
    assert decode_command(command) == PaperObserveSell(source)
    duplicate = command.replace("{", '{"kind":"wrong",', 1)
    with pytest.raises(DomainError):
        decode_command(duplicate)
    connection = sqlite3.connect(tmp_path / "gridbot-paper.sqlite3")
    connection.execute("DROP TRIGGER paper_events_no_update")
    connection.execute("UPDATE paper_events SET payload='corrupt' WHERE sequence=1")
    connection.commit()
    connection.close()
    with pytest.raises(PaperPersistenceError):
        store.recover()


@pytest.mark.parametrize("damage", ["missing_trigger", "wrong_marker", "changed_initial"])
def test_paper_schema_marker_and_initial_digest_are_independent_guards(
    tmp_path: Path, damage: str
) -> None:
    store = PaperJournal.create(tmp_path, initial())
    connection = sqlite3.connect(tmp_path / "gridbot-paper.sqlite3")
    if damage == "missing_trigger":
        connection.execute("DROP TRIGGER paper_events_no_update")
    else:
        connection.execute("DROP TRIGGER paper_meta_no_update")
        if damage == "wrong_marker":
            connection.execute("UPDATE paper_meta SET marker='OTHER_AUTHORITY'")
        else:
            changed = replace(initial().initial, initial_quote=Money.parse("21", USDT))
            connection.execute("UPDATE paper_meta SET initial=?", (encode_initial(changed),))
        connection.execute(implementation.TABLES[2])
    connection.commit()
    connection.close()
    with pytest.raises(PaperPersistenceError):
        store.recover()
