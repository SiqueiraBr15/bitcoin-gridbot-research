"""Subprocesso de teste limitado; o encerramento abrupto nunca atinge o Codex."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import cast
from unittest.mock import patch

from gridbot.application.operational_persistence import (
    OperationalScope,
    OperationalTransition,
    PersistenceError,
)
from gridbot.exchange.binance.offline_evidence import RawSellObservation
from gridbot.exchange.binance.offline_replay import OfflineSellReplayPlan
from gridbot.storage.financial_codec import decode_contract, encode_contract
from gridbot.storage.journal_paths import JournalPathPolicy
from gridbot.storage.operational_journal import SQLiteOperationalJournal


def main() -> None:
    directory, input_path, mode, point = sys.argv[1:]
    data = json.loads(Path(input_path).read_text(encoding="utf8"))
    scope = decode_contract(data["scope"])
    if type(scope) is not OperationalScope:
        raise TypeError("scope worker inválido")
    policy = JournalPathPolicy(Path(directory))

    def fault(_store: SQLiteOperationalJournal, current: str) -> None:
        if current == point:
            os._exit(71)

    if mode == "recover":
        with patch.object(SQLiteOperationalJournal, "_checkpoint", fault):
            store = SQLiteOperationalJournal.open(policy)
            recovery = store.recover(scope)
            sys.stdout.write(
                json.dumps(
                    {
                        "revision": recovery.state.revision,
                        "state": encode_contract(recovery.state.book),
                        "raw": [r.raw.payload for r in recovery.receipts],
                        "quarantines": [list(r.quarantined_sources) for r in recovery.replays],
                    }
                )
            )
        return
    store = SQLiteOperationalJournal.open(policy)
    loaded = store.load_operational_state(scope)
    if mode == "race":
        sys.stdout.write("READY\n")
        sys.stdout.flush()
        if sys.stdin.readline() != "GO\n":
            raise RuntimeError("barreira não liberada")
    try:
        with patch.object(SQLiteOperationalJournal, "_checkpoint", fault):
            revision = loaded.revision
            if data["operation"] == "transition":
                command = cast(OperationalTransition, decode_contract(data["command"]))
                raw = cast(tuple[RawSellObservation, ...], decode_contract(data["raw"]))
                result = store.commit_operational_transition(scope, revision, command, raw)
            elif data["operation"] == "raw":
                observations = cast(tuple[RawSellObservation, ...], decode_contract(data["raw"]))
                result = store.append_raw_observations(scope, revision, observations)
            elif data["operation"] == "replay":
                plan = cast(OfflineSellReplayPlan, decode_contract(data["plan"]))
                result = store.record_replay(scope, revision, plan)
            else:
                raise RuntimeError("operação worker desconhecida")
        output = {"status": "committed", "revision": result.revision}
    except PersistenceError as exc:
        output = {"status": exc.code.value}
    sys.stdout.write(json.dumps(output) + "\n")


if __name__ == "__main__":
    main()
