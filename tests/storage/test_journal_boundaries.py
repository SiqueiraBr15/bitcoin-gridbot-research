"""Fronteiras de schema/recursos antes de qualquer escrita financeira."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from gridbot.application.operational_persistence import (
    OperationalScope,
    PersistenceError,
    PersistenceErrorCode,
    VersionedOperationalState,
    apply_operational_transition,
    require_revision,
)
from gridbot.domain import BTC, BTCUSDT, USDT, Money
from gridbot.storage.financial_codec import decode_contract, encode_contract, revalidate_contract
from gridbot.storage.journal_models import DurableRawReceipt, ReceiptClassification
from gridbot.storage.journal_paths import JournalPathPolicy
from gridbot.storage.operational_journal import SQLiteOperationalJournal
from tests.application.test_offline_sell_evidence import wire_scenario
from tests.storage.test_operational_journal import bound_sell, journal_start, pristine


@pytest.mark.parametrize("value", [-1, True, 0.1, 2**63 - 1])
def test_revisions_do_not_accept_bool_float_negative_or_overflow(value: object) -> None:
    with pytest.raises(PersistenceError):
        require_revision(cast(Any, value))


@pytest.mark.parametrize("timeout", [-1, True, 5001])
def test_invalid_timeout_creates_no_empty_database(tmp_path: Path, timeout: int) -> None:
    policy = JournalPathPolicy(tmp_path)
    with pytest.raises(PersistenceError):
        SQLiteOperationalJournal.create(policy, busy_timeout_ms=timeout)
    assert not policy.database_path().exists()


@pytest.mark.parametrize(
    "parts",
    [
        [2, "1", 0],
        [True, "1", 0],
        [0, "NaN", 0],
        [0, "\uff11\uff12", 0],
        [0, "", 0],
        [0, "1", True],
        [0, "1", 10**30],
        [0, "001", 0],
        [0],
    ],
)
def test_malformed_decimal_representation_is_not_coerced(parts: list[object]) -> None:
    payload = json.dumps({"schema": 1, "value": {"decimal": parts}})
    with pytest.raises(PersistenceError) as error:
        decode_contract(payload)
    assert error.value.code is PersistenceErrorCode.INVALID_DECIMAL


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_non_finite_decimal_cannot_enter_persistent_format(value: Decimal) -> None:
    with pytest.raises(PersistenceError):
        encode_contract(value)


def test_json_numeric_float_is_rejected_before_schema_interpretation() -> None:
    with pytest.raises(PersistenceError) as error:
        decode_contract('{"schema":1.0,"value":null}')
    assert error.value.code is PersistenceErrorCode.CORRUPT_JSON


@pytest.mark.parametrize(
    "value",
    [
        [],
        {"tuple": "not-array"},
        {"enum": ["Unknown", "BUY"]},
        {"enum": ["Side", "UNKNOWN"]},
        {"enum": [True]},
        {"other": 0},
    ],
)
def test_unknown_nested_tags_and_enums_do_not_run_imports(value: object) -> None:
    with pytest.raises(PersistenceError):
        decode_contract(json.dumps({"schema": 1, "value": value}))


def test_resource_limits_refuse_instead_of_truncating() -> None:
    nested: object = 0
    for _ in range(100):
        nested = (nested,)
    with pytest.raises(PersistenceError) as depth:
        encode_contract(nested)
    assert depth.value.code is PersistenceErrorCode.LIMIT_EXCEEDED
    with pytest.raises(PersistenceError) as coefficient:
        encode_contract(Decimal("9" * 4097))
    assert coefficient.value.code is PersistenceErrorCode.LIMIT_EXCEEDED
    with pytest.raises(PersistenceError) as text:
        decode_contract(" " * 16_000_001)
    assert text.value.code is PersistenceErrorCode.LIMIT_EXCEEDED


def test_roundtrip_requires_the_requested_closed_contract() -> None:
    with pytest.raises(PersistenceError):
        revalidate_contract(cast(Any, Money.parse("1", USDT)), OperationalScope)
    with pytest.raises(PersistenceError):
        apply_operational_transition(pristine(), cast(Any, object()))


@pytest.mark.parametrize("alias", ["", "bad\nref", " bad", "x" * 129])
def test_scope_alias_and_nested_symbol_are_validated(alias: str) -> None:
    with pytest.raises(PersistenceError):
        OperationalScope("BINANCE_SPOT", alias, "synthetic", BTCUSDT)


def test_scope_state_and_binding_financial_mismatch_are_blocked(tmp_path: Path) -> None:
    store, state = bound_sell(tmp_path)
    with pytest.raises(PersistenceError):
        VersionedOperationalState(
            replace(state.scope, account_ref="other"), state.revision, state.book
        )
    from gridbot.domain import Symbol

    foreign_symbol = Symbol(BTC, type(USDT)("EUR"))
    with pytest.raises(PersistenceError):
        VersionedOperationalState(
            replace(state.scope, symbol=foreign_symbol), state.revision, state.book
        )
    with pytest.raises(PersistenceError):
        store.append_raw_observations(state.scope, state.revision, ())
    with pytest.raises(PersistenceError):
        store.append_raw_observations(state.scope, state.revision, cast(Any, []))
    assert store.load_operational_state(state.scope) == state


@pytest.mark.parametrize("change", ["zero-sequence", "unknown-classification", "future-duplicate"])
def test_receipt_cannot_claim_invalid_origin_or_sequence(change: str) -> None:
    raw = wire_scenario().tape.observations[0]
    changes: dict[str, Any] = {
        "sequence": 0 if change == "zero-sequence" else 2,
        "revision": 1,
        "raw": raw,
        "classification": "RECEIVED"
        if change == "unknown-classification"
        else ReceiptClassification.RECEIVED,
        "duplicate_of": 3 if change == "future-duplicate" else None,
    }
    with pytest.raises((PersistenceError, TypeError)):
        DurableRawReceipt(**changes)


def test_missing_scope_and_path_metadata_fail_without_bootstrap(tmp_path: Path) -> None:
    store, state = journal_start(tmp_path)
    with pytest.raises(PersistenceError) as error:
        store.load_operational_state(replace(state.scope, account_ref="unknown"))
    assert error.value.code is PersistenceErrorCode.NOT_FOUND
    with pytest.raises(PersistenceError):
        JournalPathPolicy(tmp_path, cast(Any, {"OneDrive": str(tmp_path)}))
    with pytest.raises(PersistenceError):
        JournalPathPolicy(tmp_path, (("OneDrive", ""), ("OneDrive", "")))
    assert store.load_operational_state(state.scope) == state
