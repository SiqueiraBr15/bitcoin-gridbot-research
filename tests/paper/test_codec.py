"""Permanent negative contracts from the transition probes, not coverage-only stubs."""

import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from typing import Any, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import gridbot.storage.financial_codec as financial_codec
from gridbot.application.operational_persistence import PersistenceError, PersistenceErrorCode
from gridbot.application.sell_lifecycle import SellExecutionRef
from gridbot.application.sell_terminal import SellTerminalReconciliation
from gridbot.domain import USDT, Money
from gridbot.paper.accounting import (
    PaperApplySell,
    PaperError,
    PaperErrorCode,
    PaperObserveSell,
    PaperReleaseNoFill,
)
from gridbot.storage.financial_codec import encode_contract
from gridbot.storage.paper_codec import (
    MARKER,
    MAX_TEXT,
    PaperCodecCode,
    PaperCodecError,
    decode_command,
    decode_initial,
    encode_command,
    encode_initial,
)
from tests.paper.fixtures import bought, commit, evidence, initial, reserve_sell


def envelope(kind: object, payload: object, **changes: object) -> str:
    obj = {"paper_schema": MARKER, "kind": kind, "payload": encode_contract(payload)}
    obj.update(changes)
    return json.dumps(obj, separators=(",", ":"))


@pytest.fixture(scope="module")
def source_values() -> tuple[Any, ...]:
    book, execution = reserve_sell(bought())
    source = evidence(book, execution)
    r = source.reconciliation
    assert r.ledger is not None
    return (
        source.account.ref,
        source.source_revision,
        r.book,
        r.cycle_ref,
        (r.ledger.context, r.ledger.fills),
        r.report,
        r.collection,
        r.source_findings,
    )


@pytest.mark.parametrize(
    "text",
    ["[]", "null", "{}", '{"paper_schema":"unknown","kind":"initial","payload":"x"}'],
)
def test_unknown_root_and_version_fail_closed(text: str) -> None:
    with pytest.raises(PaperCodecError) as error:
        decode_command(text)
    assert error.value.code is PaperCodecCode.UNKNOWN_SCHEMA


@pytest.mark.parametrize("change", ["version", "missing", "extra", "kind-type", "initial-kind"])
def test_exact_envelope_contract(change: str) -> None:
    data = json.loads(envelope("PaperApplySell", ()))
    if change == "version":
        data["paper_schema"] = MARKER + "2"
    elif change == "missing":
        del data["payload"]
    elif change == "extra":
        data["balance"] = "1000000"
    elif change == "kind-type":
        data["kind"] = 1
    decoder = decode_initial if change == "initial-kind" else decode_command
    with pytest.raises(PaperCodecError) as error:
        decoder(json.dumps(data))
    assert error.value.code is PaperCodecCode.UNKNOWN_SCHEMA


@pytest.mark.parametrize("text", ["{", "", '{"kind":"a","kind":"b"}', "[" * 1200])
def test_malformed_duplicate_and_parser_depth_have_typed_errors(text: str) -> None:
    with pytest.raises(PaperCodecError) as error:
        decode_command(text)
    assert error.value.code is PaperCodecCode.INVALID_JSON


@pytest.mark.parametrize("case", ["payload", "initial-fields", "command-fields", "unknown-command"])
def test_source_shapes_never_supply_missing_financial_defaults(case: str) -> None:
    if case == "payload":
        text = envelope("PaperApplySell", Money.zero(USDT))
    elif case == "initial-fields":
        x = initial().initial
        text = envelope("initial", (x.account.ref, x.grid_state, x.rules, x.initial_quote))
    elif case == "command-fields":
        text = envelope("PaperApplySell", (SellExecutionRef("PAPER:demo:SELL:a"),))
    else:
        text = envelope("PaperUnknown", ())
    with pytest.raises(PaperCodecError) as error:
        (decode_initial if case == "initial-fields" else decode_command)(text)
    assert error.value.code is (
        PaperCodecCode.UNKNOWN_SCHEMA if case == "unknown-command" else PaperCodecCode.INVALID_INPUT
    )


@pytest.mark.parametrize("case", ["observation-fields", "ledger-type", "ledger-fields"])
def test_observation_cannot_drop_ledger_shape(case: str, source_values: tuple[Any, ...]) -> None:
    values = source_values
    if case == "observation-fields":
        values = values[:-1]
    elif case == "ledger-type":
        values = (*values[:4], "wrong", *values[5:])
    else:
        values = (*values[:4], (values[4][0],), *values[5:])
    with pytest.raises(PaperCodecError) as error:
        decode_command(envelope("PaperObserveSell", values))
    assert error.value.code is PaperCodecCode.INVALID_INPUT


@pytest.mark.parametrize("initial_encoder", [False, True])
def test_foreign_authority_cannot_be_encoded(initial_encoder: bool) -> None:
    with pytest.raises(PaperCodecError) as error:
        (encode_initial if initial_encoder else encode_command)(cast(Any, object()))
    assert error.value.code is PaperCodecCode.INVALID_INPUT


def test_all_command_roundtrips_and_pending_ledger_is_not_credit() -> None:
    original = initial()
    book, execution = reserve_sell(bought(original))
    source = evidence(book, execution)
    assert decode_initial(encode_initial(original.initial)) == original.initial
    for command in (
        *book.entries,
        PaperObserveSell(source),
        PaperApplySell(execution, 4),
        PaperReleaseNoFill(execution),
    ):
        assert decode_command(encode_command(command)) == command
    r = source.reconciliation
    pending = replace(
        source,
        reconciliation=SellTerminalReconciliation(
            r.book, r.cycle_ref, None, r.report, r.collection
        ),
    )
    decoded = decode_command(encode_command(PaperObserveSell(pending)))
    assert isinstance(decoded, PaperObserveSell)
    assert decoded.evidence.assessment.projection is None
    recorded = commit(book, decoded)
    with pytest.raises(PaperError) as error:
        commit(recorded, PaperApplySell(execution, recorded.revision))
    assert error.value.code is PaperErrorCode.EVIDENCE_PENDING
    assert recorded.settled_sell_proceeds == Money.zero(USDT)
    assert recorded.reserved_grid_base == book.reserved_grid_base


def test_v1_canonical_initial_remains_byte_compatible_with_a18_1() -> None:
    # Golden digest independently obtained from f5cf2e2, not regenerated by the test.
    assert hashlib.sha256(encode_initial(initial().initial).encode("ascii")).hexdigest() == (
        "7bac78a9a9c39cd9e56ded91c34b1be8ba27d22f62643d682201afafd19206a9"
    )


@pytest.mark.parametrize("suffix", ["ascii", "é", "😀", "e\u0301", "a\x01b", 'a"\\b'])
def test_unicode_and_escapes_preserve_identity_and_charge_utf8_bytes(suffix: str) -> None:
    command = PaperApplySell(SellExecutionRef("PAPER:demo:SELL:" + suffix), 1)
    canonical = encode_command(command)
    assert canonical.isascii()
    assert decode_command(canonical) == command
    obj = json.loads(canonical)
    obj["payload"] = json.dumps(json.loads(obj["payload"]), ensure_ascii=False)
    unescaped = json.dumps(obj, ensure_ascii=False)
    assert decode_command(unescaped) == command
    exact = unescaped + " " * (MAX_TEXT - len(unescaped.encode("utf8")))
    assert decode_command(exact) == command
    with pytest.raises(PaperCodecError) as error:
        decode_command(exact + " ")
    assert error.value.code is PaperCodecCode.LIMIT_EXCEEDED


@pytest.mark.parametrize("text", [None, b"{}", 1])
def test_non_text_input_is_typed(text: object) -> None:
    with pytest.raises(PaperCodecError) as error:
        decode_command(cast(Any, text))
    assert error.value.code is PaperCodecCode.INVALID_INPUT


def test_encoded_size_and_raw_size_limits_are_independent() -> None:
    command = PaperApplySell(SellExecutionRef("PAPER:demo:SELL:a"), cast(Any, "x" * MAX_TEXT))
    with pytest.raises(PaperCodecError) as error:
        encode_command(command)
    assert error.value.code is PaperCodecCode.LIMIT_EXCEEDED
    with pytest.raises(PaperCodecError) as error:
        decode_command("x" * (MAX_TEXT + 1))
    assert error.value.code is PaperCodecCode.LIMIT_EXCEEDED


@pytest.mark.parametrize("surrogate", [chr(0xD800), chr(0xDFFF), "a" + chr(0xD800) + "b"])
def test_invalid_surrogates_are_rejected_even_when_json_escaped(surrogate: str) -> None:
    command = PaperApplySell(SellExecutionRef("PAPER:demo:SELL:" + surrogate), 1)
    with pytest.raises(PaperCodecError) as error:
        encode_command(command)
    assert error.value.code is PaperCodecCode.INVALID_JSON
    text = envelope("PaperApplySell", (command.execution_ref, 1))
    with pytest.raises(PaperCodecError) as error:
        decode_command(text)
    assert error.value.code is PaperCodecCode.INVALID_JSON
    with pytest.raises(PaperCodecError):
        decode_command(surrogate)


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("1" * 4097)])
def test_decimal_graph_limits_preserve_financial_error_codes(value: Decimal) -> None:
    with pytest.raises(PersistenceError) as error:
        envelope("PaperApplySell", (value,))
    assert error.value.code in {
        PersistenceErrorCode.INVALID_DECIMAL,
        PersistenceErrorCode.LIMIT_EXCEEDED,
    }


def test_nested_graph_and_real_node_budget_fail_closed() -> None:
    nested: object = ()
    for _ in range(98):
        nested = (nested,)
    with pytest.raises(PersistenceError) as error:
        envelope("PaperApplySell", nested)
    assert error.value.code is PersistenceErrorCode.LIMIT_EXCEEDED
    with pytest.raises(PersistenceError) as error:
        envelope("PaperApplySell", (None,) * 500_001)
    assert error.value.code is PersistenceErrorCode.LIMIT_EXCEEDED
    assert financial_codec._MAX_DEPTH == 96
    assert financial_codec._MAX_NODES == 500_000


@pytest.mark.parametrize("malformation", ["depth", "nodes", "decimal-digits", "decimal-exponent"])
def test_incoming_graph_resource_guards_preserve_typed_codes(malformation: str) -> None:
    value: object
    if malformation == "depth":
        value = {"tuple": []}
        for _ in range(98):
            value = {"tuple": [value]}
    elif malformation == "nodes":
        value = {"tuple": [0] * 500_001}
    elif malformation == "decimal-digits":
        value = {"decimal": [0, "1" * 4097, 0]}
    else:
        value = {"decimal": [0, "1", 10**100]}
    payload = json.dumps({"schema": 1, "value": value}, separators=(",", ":"))
    text = json.dumps({"paper_schema": MARKER, "kind": "PaperApplySell", "payload": payload})
    assert len(text.encode("utf8")) < MAX_TEXT
    with pytest.raises(PersistenceError) as error:
        decode_command(text)
    assert error.value.code is (
        PersistenceErrorCode.LIMIT_EXCEEDED
        if malformation in {"depth", "nodes"}
        else PersistenceErrorCode.INVALID_DECIMAL
    )


def test_float_revision_rejected_by_encoding_and_by_authority() -> None:
    book, execution = reserve_sell(bought())
    invalid = PaperApplySell(execution, cast(Any, 4.0))
    with pytest.raises(PersistenceError) as error:
        encode_command(invalid)
    assert error.value.code is PersistenceErrorCode.INVALID_STATE
    with pytest.raises(PersistenceError) as error:
        commit(book, invalid)
    assert error.value.code is PersistenceErrorCode.INVALID_STATE


@settings(max_examples=12, derandomize=True, deadline=None)
@given(suffix=st.text(alphabet="aé😀e\u0301", min_size=1, max_size=30))
def test_generated_scalar_unicode_roundtrip_preserves_exact_ref(suffix: str) -> None:
    command = PaperApplySell(SellExecutionRef("PAPER:demo:SELL:" + suffix), 1)
    assert decode_command(encode_command(command)) == command
