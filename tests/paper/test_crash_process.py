"""Actual bounded process deaths on the isolated PAPER database only."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from gridbot.paper.accounting import PaperApplySell, PaperObserveSell
from gridbot.storage.paper_journal import PaperJournal
from tests.paper.fixtures import commit
from tests.paper.test_journal import persisted


@pytest.mark.parametrize("boundary", ["_before_commit", "_after_commit"])
def test_process_death_recovers_one_atomic_paper_result(tmp_path: Path, boundary: str) -> None:
    store, book, execution, source = persisted(tmp_path)
    book = store.commit(book.revision, PaperObserveSell(source))
    command = PaperApplySell(execution, book.revision)
    expected = commit(book, command)
    program = """
import os,sys
from pathlib import Path
import gridbot.storage.paper_journal as module
from gridbot.paper.accounting import PaperApplySell
from gridbot.application.sell_lifecycle import SellExecutionRef
store=module.PaperJournal.open(Path(sys.argv[1]))
book=store.recover()
setattr(module,sys.argv[2],lambda connection:os._exit(73))
store.commit(book.revision,PaperApplySell(SellExecutionRef(sys.argv[3]),book.revision))
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path), boundary, execution.value],
        env=dict(os.environ, PYTHONUTF8="1"),
        capture_output=True,
        text=True,
        encoding="utf8",
        timeout=30,
    )
    assert result.returncode == 73, result.stdout + result.stderr
    restored = PaperJournal.open(tmp_path).recover()
    assert restored == (book if boundary == "_before_commit" else expected)
    if boundary == "_after_commit":
        assert store.commit(restored.revision, command) == restored
