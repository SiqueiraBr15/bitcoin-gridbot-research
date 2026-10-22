"""Workers A17.4 com protocolo stdin/stdout, somente em diretórios de fixture."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from gridbot.application.operational_persistence import (
    OperationalScope,
    PersistenceError,
)
from gridbot.storage.financial_codec import decode_contract, encode_contract
from gridbot.storage.journal_paths import JournalPathPolicy
from gridbot.storage.operational_journal import SQLiteOperationalJournal
from tests.application.test_offline_sell_evidence import wire_scenario
from tests.application.test_operational_grid import ref
from tests.storage.test_operational_journal import funded_plan


def emit(value: object) -> None:
    sys.stdout.write(json.dumps(value) + "\n")
    sys.stdout.flush()


def receive(expected: str) -> None:
    if sys.stdin.readline().strip() != expected:
        raise RuntimeError("worker barrier failed")


def main() -> None:
    directory, scope_file, mode, operation, point = sys.argv[1:]
    scope = decode_contract(Path(scope_file).read_text(encoding="utf8"))
    assert type(scope) is OperationalScope
    if mode == "recover":
        emit({"ready": True})
        receive("GO")
        store = SQLiteOperationalJournal.open(JournalPathPolicy(Path(directory)))
        recovered = store.recover(scope)
        emit(
            {
                "revision": recovered.state.revision,
                "book": encode_contract(recovered.state.book),
                "raw": len(recovered.receipts),
            }
        )
        return
    store = SQLiteOperationalJournal.open(JournalPathPolicy(Path(directory)))
    state = store.load_operational_state(scope)
    if mode == "reader":
        with store._session(write=False) as connection:
            before = store._read(connection, scope)
            emit({"ready": True, "revision": before.state.revision})
            receive("CHECK")
            after = store._read(connection, scope)
            assert after == before
            emit({"same_snapshot": True})
        return
    source = wire_scenario()
    command = replace(funded_plan(state), cycle_ref=ref(1))
    raw = source.tape.observations[0]
    if operation == "conflict":
        raw = replace(raw, payload="[]")
    if mode in {"crash", "staged"}:

        def checkpoint(_self: SQLiteOperationalJournal, name: str) -> None:
            if name == point:
                if mode == "crash":
                    os._exit(77)
                emit({"staged": True})
                receive("COMMIT")

    else:
        emit({"ready": True, "revision": state.revision})
        receive("GO")

    def perform() -> None:
        try:
            if operation == "finance":
                result = store.commit_operational_transition(
                    scope,
                    state.revision,
                    command,
                    source.tape.observations if mode == "crash" else (),
                )
            else:
                result = store.append_raw_observation(scope, state.revision, raw)
            emit({"status": "COMMITTED", "revision": result.revision})
        except PersistenceError as error:
            emit({"status": error.code.value})

    if mode in {"crash", "staged"}:
        with patch.object(SQLiteOperationalJournal, "_checkpoint", checkpoint):
            perform()
    else:
        perform()


if __name__ == "__main__":
    main()
