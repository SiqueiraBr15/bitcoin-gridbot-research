"""Closed PAPER envelopes. Production registry is unchanged and rejects PAPER authorities."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from enum import StrEnum
from typing import Any, cast

from gridbot.application.sell_fills import SellFillLedger
from gridbot.application.sell_terminal import SellTerminalReconciliation
from gridbot.domain.errors import DomainError
from gridbot.paper.accounting import (
    COMMAND_TYPES,
    PaperAccount,
    PaperCommand,
    PaperInitialState,
    PaperObserveSell,
    PaperSellEvidence,
)
from gridbot.storage.financial_codec import decode_contract, encode_contract

MARKER = "GRIDBOT_PAPER_ACCOUNTING_181_V1"
MAX_TEXT = 2_000_000
# MAX_TEXT is a UTF-8 byte budget for the complete JSON envelope, including escapes.
# The ASCII canonical writer and the persisted V1 representation remain unchanged.


class PaperCodecCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    INVALID_JSON = "INVALID_JSON"
    UNKNOWN_SCHEMA = "UNKNOWN_SCHEMA"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"


class PaperCodecError(DomainError):
    def __init__(self, code: PaperCodecCode, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def text_bytes(text: str) -> int:
    """Bound allocation before encoding; reject non-scalar Unicode and oversized UTF-8."""
    if type(text) is not str:
        raise PaperCodecError(PaperCodecCode.INVALID_INPUT, "PAPER text required")
    if len(text) > MAX_TEXT:
        raise PaperCodecError(PaperCodecCode.LIMIT_EXCEEDED, "PAPER envelope exceeds UTF-8 bytes")
    try:
        size = len(text.encode("utf8"))
    except UnicodeError as exc:
        raise PaperCodecError(PaperCodecCode.INVALID_JSON, "PAPER invalid Unicode") from exc
    if size > MAX_TEXT:
        raise PaperCodecError(PaperCodecCode.LIMIT_EXCEEDED, "PAPER envelope exceeds UTF-8 bytes")
    return size


def _unicode_source(value: object) -> None:
    # Called only after the closed financial codec has bounded nodes/depth and types.
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is str:
            try:
                item.encode("utf8")
            except UnicodeError as exc:
                raise PaperCodecError(
                    PaperCodecCode.INVALID_JSON, "PAPER source invalid Unicode"
                ) from exc
        elif isinstance(item, tuple):
            pending.extend(item)
        elif is_dataclass(item) and not isinstance(item, type):
            pending.extend(getattr(item, f.name) for f in fields(item))


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PaperCodecError(PaperCodecCode.INVALID_JSON, "duplicate PAPER JSON key")
        result[key] = value
    return result


def _envelope(kind: str, payload: object) -> str:
    encoded = encode_contract(payload)
    _unicode_source(payload)
    text = json.dumps(
        {"paper_schema": MARKER, "kind": kind, "payload": encoded},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    text_bytes(text)
    return text


def _parse(text: str, kind: str | None = None) -> tuple[str, tuple[Any, ...]]:
    text_bytes(text)
    try:
        obj = json.loads(text, object_pairs_hook=_pairs)
    except PaperCodecError:
        raise
    except (ValueError, RecursionError) as exc:
        raise PaperCodecError(PaperCodecCode.INVALID_JSON, "PAPER malformed JSON") from exc
    if (
        type(obj) is not dict
        or set(obj) != {"paper_schema", "kind", "payload"}
        or obj["paper_schema"] != MARKER
        or type(obj["kind"]) is not str
        or (kind is not None and obj["kind"] != kind)
    ):
        raise PaperCodecError(PaperCodecCode.UNKNOWN_SCHEMA, "foreign/unknown PAPER envelope")
    value = decode_contract(obj["payload"])
    _unicode_source(value)
    if type(value) is not tuple:
        raise PaperCodecError(PaperCodecCode.INVALID_INPUT, "PAPER source tuple required")
    return obj["kind"], value


def encode_initial(initial: PaperInitialState) -> str:
    if type(initial) is not PaperInitialState:
        raise PaperCodecError(PaperCodecCode.INVALID_INPUT, "PAPER initial required")
    return _envelope(
        "initial",
        (
            initial.account.ref,
            initial.grid_state,
            initial.rules,
            initial.initial_quote,
            initial.third_asset_funding,
        ),
    )


def decode_initial(text: str) -> PaperInitialState:
    _, values = _parse(text, "initial")
    if len(values) != 5:
        raise PaperCodecError(PaperCodecCode.INVALID_INPUT, "PAPER initial fields")
    return PaperInitialState(PaperAccount(values[0]), *values[1:])


def encode_command(command: PaperCommand) -> str:
    if type(command) not in COMMAND_TYPES:
        raise PaperCodecError(PaperCodecCode.INVALID_INPUT, "non-PAPER command")
    if isinstance(command, PaperObserveSell):
        e = command.evidence
        r = e.reconciliation
        ledger = None if r.ledger is None else (r.ledger.context, r.ledger.fills)
        payload: object = (
            e.account.ref,
            e.source_revision,
            r.book,
            r.cycle_ref,
            ledger,
            r.report,
            r.collection,
            r.source_findings,
        )
    else:
        payload = tuple(getattr(command, f.name) for f in fields(command))
    return _envelope(type(command).__name__, payload)


def decode_command(text: str) -> PaperCommand:
    kind, values = _parse(text)
    constructors = {cls.__name__: cls for cls in COMMAND_TYPES}
    if kind not in constructors:
        raise PaperCodecError(PaperCodecCode.UNKNOWN_SCHEMA, "unknown PAPER command")
    if kind == "PaperObserveSell":
        if len(values) != 8:
            raise PaperCodecError(PaperCodecCode.INVALID_INPUT, "PAPER observation fields")
        account, revision, root, ref, source_ledger, report, collection, findings = values
        if source_ledger is not None and (
            type(source_ledger) is not tuple or len(source_ledger) != 2
        ):
            raise PaperCodecError(PaperCodecCode.INVALID_INPUT, "PAPER ledger tuple")
        ledger = None if source_ledger is None else SellFillLedger(*source_ledger)
        return PaperObserveSell(
            PaperSellEvidence(
                PaperAccount(account),
                revision,
                SellTerminalReconciliation(root, ref, ledger, report, collection, findings),
            )
        )
    cls = constructors[kind]
    if len(values) != len(fields(cls)):
        raise PaperCodecError(PaperCodecCode.INVALID_INPUT, "PAPER command fields")
    return cast(PaperCommand, cast(Any, cls)(*values))
