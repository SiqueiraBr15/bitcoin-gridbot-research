"""Schema 1 explícito do grafo A11 a A17.3. Sem imports controlados por dados."""

from __future__ import annotations

import json
from dataclasses import fields
from decimal import Decimal, DecimalException
from enum import StrEnum
from typing import Any

from gridbot.application.buy_lifecycle import BuyAttempt, BuyAttemptStatus, BuyLifecycleBook
from gridbot.application.buy_quote_capital import BuyQuoteReservation, FundedBuyBook
from gridbot.application.operational_grid import GridOperationalBook
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
from gridbot.application.sell_evidence import (
    CollectedSellTrade,
    ObservedSellOrderReport,
    SellCollectionStopReason,
    SellOrderIdentity,
    SellTradeCollection,
    SellTradeIdentityCoverage,
    SellTradePage,
    SellTradePagination,
    SellTradeQueryScope,
)
from gridbot.application.sell_fills import ObservedSellFill
from gridbot.application.sell_intents import GridSellIntent, SellIntentPlan
from gridbot.application.sell_inventory import SellBaseInventoryReservation, SellInventoryBook
from gridbot.application.sell_lifecycle import (
    SellAttempt,
    SellAttemptStatus,
    SellExecutionContext,
    SellExecutionRef,
)
from gridbot.application.sell_order_binding import ExternalSellOrderBinding
from gridbot.application.sell_reconciliation import (
    SellFindingKind,
    SellReconciliationCode,
    SellReconciliationFinding,
)
from gridbot.domain.assets import Asset, Symbol
from gridbot.domain.enums import LiquidityRole, OrderStatus, OrderType, Side
from gridbot.domain.errors import DomainError
from gridbot.domain.grid import GridLevel
from gridbot.domain.rules import MarketRules, NotionalRules, PriceRules, QuantityRules
from gridbot.domain.values import Money, Price, Qty
from gridbot.exchange.binance.offline_evidence import (
    NormalizedSellObservation,
    OfflineIssueCode,
    OfflineSellIssue,
    OfflineSellSource,
    RawSellObservation,
)
from gridbot.exchange.binance.offline_replay import OfflineSellReplayPlan
from gridbot.portfolio.buy_fills import BuyFillLedger, ObservedBuyFill
from gridbot.portfolio.buy_finalization import (
    BuyExecutionContext,
    BuyExecutionRef,
    BuyExecutionStatus,
    BuyFillReconciliationEvidence,
    FinalizedBuy,
    ObservedBuyTerminalReport,
)
from gridbot.portfolio.sell_sizing import SellSizingAssessment
from gridbot.storage.journal_models import (
    DurableRawReceipt,
    DurableReplayRecord,
    ReceiptClassification,
)
from gridbot.strategy.arithmetic_grid import ArithmeticGridPlan, ArithmeticGridSpec
from gridbot.strategy.buy_intents import BuyIntentPlan, GridBuyIntent
from gridbot.strategy.grid_sizing import CellAllocation, GridSizingPlan, SizingPolicy
from gridbot.strategy.grid_state import CellCycleRef, CellPhase, CellState, GridCell, GridState

_CONTRACTS: dict[str, tuple[type[Any], tuple[str, ...]]] = {
    "Asset": (Asset, ("code",)),
    "Symbol": (Symbol, ("base", "quote")),
    "Price": (Price, ("value",)),
    "Qty": (Qty, ("value",)),
    "Money": (Money, ("amount", "asset")),
    "GridLevel": (GridLevel, ("index", "price")),
    "PriceRules": (PriceRules, ("tick_size", "min_price", "max_price")),
    "QuantityRules": (QuantityRules, ("step_size", "min_qty", "max_qty")),
    "NotionalRules": (NotionalRules, ("min_notional", "max_notional")),
    "MarketRules": (MarketRules, ("symbol", "price", "quantity", "notional")),
    "ArithmeticGridSpec": (
        ArithmeticGridSpec,
        ("symbol", "lower_price", "upper_price", "interval_count"),
    ),
    "ArithmeticGridPlan": (ArithmeticGridPlan, ("spec", "tick_size", "levels")),
    "CellCycleRef": (CellCycleRef, ("cell_index", "cycle_seq")),
    "GridCell": (GridCell, ("index", "buy_level", "sell_level")),
    "CellState": (CellState, ("cell", "phase", "buy_armed", "cycle_seq")),
    "GridState": (GridState, ("plan", "cells")),
    "CellAllocation": (CellAllocation, ("cycle_ref", "buy_price", "qty", "notional")),
    "GridSizingPlan": (
        GridSizingPlan,
        (
            "symbol",
            "policy",
            "step_size",
            "spendable_quote_budget",
            "bundle_count",
            "qty_per_cell",
            "allocations",
            "allocated_quote",
            "unallocated_quote",
        ),
    ),
    "GridBuyIntent": (GridBuyIntent, ("cycle_ref", "symbol", "price", "qty", "side", "order_type")),
    "BuyIntentPlan": (BuyIntentPlan, ("symbol", "sizing", "intents")),
    "ObservedBuyFill": (
        ObservedBuyFill,
        (
            "fill_ref",
            "cycle_ref",
            "symbol",
            "execution_price",
            "executed_qty",
            "fee",
            "liquidity",
            "side",
        ),
    ),
    "BuyFillLedger": (BuyFillLedger, ("intent", "fills")),
    "BuyExecutionRef": (BuyExecutionRef, ("value",)),
    "BuyExecutionContext": (BuyExecutionContext, ("intent", "execution_ref")),
    "ObservedBuyTerminalReport": (
        ObservedBuyTerminalReport,
        (
            "execution_ref",
            "symbol",
            "cycle_ref",
            "final_status",
            "cumulative_executed_qty",
            "fill_refs",
        ),
    ),
    "BuyFillReconciliationEvidence": (
        BuyFillReconciliationEvidence,
        ("execution_ref", "symbol", "cycle_ref", "cumulative_executed_qty", "fill_refs"),
    ),
    "FinalizedBuy": (
        FinalizedBuy,
        ("context", "ledger", "terminal_report", "reconciliation_evidence"),
    ),
    "SellSizingAssessment": (SellSizingAssessment, ("finalized_buy", "grid_state", "market_rules")),
    "BuyAttempt": (BuyAttempt, ("intent", "status", "execution")),
    "BuyLifecycleBook": (BuyLifecycleBook, ("grid_state", "attempts", "consumed")),
    "BuyQuoteReservation": (BuyQuoteReservation, ("intent", "quote_fee_hold")),
    "FundedBuyBook": (
        FundedBuyBook,
        ("lifecycle", "initial_quote_capital", "reservations", "settled_reservations"),
    ),
    "SellBaseInventoryReservation": (SellBaseInventoryReservation, ("assessment", "base_fee_hold")),
    "SellInventoryBook": (SellInventoryBook, ("funded_buy_book", "reservations")),
    "GridSellIntent": (GridSellIntent, ("reservation",)),
    "SellIntentPlan": (SellIntentPlan, ("book", "cycle_refs")),
    "SellExecutionRef": (SellExecutionRef, ("value",)),
    "SellExecutionContext": (SellExecutionContext, ("intent", "execution_ref")),
    "SellAttempt": (SellAttempt, ("intent", "status", "execution")),
    "GridOperationalBook": (
        GridOperationalBook,
        ("inventory_book", "sell_attempts", "external_sell_bindings"),
    ),
    "ExternalSellOrderBinding": (ExternalSellOrderBinding, ("identity", "side")),
    "SellOrderIdentity": (
        SellOrderIdentity,
        (
            "venue_ref",
            "account_ref",
            "environment_ref",
            "order_ref",
            "execution_ref",
            "cycle_ref",
            "symbol",
            "client_order_ref",
        ),
    ),
    "ObservedSellOrderReport": (
        ObservedSellOrderReport,
        (
            "identity",
            "status",
            "original_qty",
            "cumulative_executed_qty",
            "cumulative_quote",
            "limit_price",
            "side",
            "order_type",
            "source_ref",
            "collection_ref",
        ),
    ),
    "CollectedSellTrade": (
        CollectedSellTrade,
        (
            "identity",
            "trade_ref",
            "execution_price",
            "executed_qty",
            "observed_quote",
            "fee",
            "side",
            "liquidity",
            "identity_coverage",
        ),
    ),
    "SellTradePage": (
        SellTradePage,
        (
            "source_ref",
            "cursor_from",
            "next_cursor",
            "trades",
            "query_identity",
            "collection_ref",
            "requested_limit",
        ),
    ),
    "SellTradeQueryScope": (
        SellTradeQueryScope,
        ("identity", "collection_ref", "pagination", "initial_cursor", "limit"),
    ),
    "SellTradeCollection": (
        SellTradeCollection,
        ("identity", "pages", "stop_reason", "order_before", "order_after", "query"),
    ),
    "ObservedSellFill": (
        ObservedSellFill,
        (
            "execution_ref",
            "fill_ref",
            "cycle_ref",
            "symbol",
            "execution_price",
            "executed_qty",
            "observed_quote",
            "fee",
            "liquidity",
            "side",
        ),
    ),
    "SellReconciliationFinding": (
        SellReconciliationFinding,
        ("code", "kind", "source", "expected", "observed"),
    ),
    "OperationalScope": (
        OperationalScope,
        ("venue_ref", "account_ref", "environment_ref", "symbol"),
    ),
    "VersionedOperationalState": (VersionedOperationalState, ("scope", "revision", "book")),
    "PrepareOperationalBuy": (PrepareOperationalBuy, ("plan", "cycle_ref", "quote_fee_hold")),
    "BindOperationalBuy": (BindOperationalBuy, ("cycle_ref", "context")),
    "MarkOperationalBuyUncertain": (MarkOperationalBuyUncertain, ("cycle_ref",)),
    "SettleOperationalBuy": (SettleOperationalBuy, ("finalized",)),
    "ReserveOperationalSell": (ReserveOperationalSell, ("assessment", "base_fee_hold")),
    "PrepareOperationalSell": (PrepareOperationalSell, ("plan", "cycle_ref")),
    "MarkOperationalSellUncertain": (MarkOperationalSellUncertain, ("cycle_ref",)),
    "BindOperationalSell": (BindOperationalSell, ("cycle_ref", "context")),
    "BindOperationalExternalSell": (BindOperationalExternalSell, ("cycle_ref", "binding")),
    "RawSellObservation": (
        RawSellObservation,
        (
            "source_ref",
            "kind",
            "scope",
            "payload",
            "collection_ref",
            "cursor_from",
            "next_cursor",
            "requested_limit",
        ),
    ),
    "NormalizedSellObservation": (
        NormalizedSellObservation,
        ("raw", "report", "trades", "issues", "unknown_fields", "non_trade"),
    ),
    "OfflineSellIssue": (OfflineSellIssue, ("code", "source_ref", "field", "detail")),
    "OfflineSellReplayPlan": (
        OfflineSellReplayPlan,
        (
            "query",
            "report_ref",
            "before_ref",
            "after_ref",
            "page_refs",
            "stop_reason",
            "event_refs",
        ),
    ),
    "DurableRawReceipt": (
        DurableRawReceipt,
        ("sequence", "revision", "raw", "classification", "duplicate_of"),
    ),
    "DurableReplayRecord": (
        DurableReplayRecord,
        (
            "plan",
            "input_revision",
            "receipt_sequences",
            "normalized",
            "issues",
            "quarantined_sources",
            "fills",
            "findings",
        ),
    ),
}

_ENUMS: dict[str, type[StrEnum]] = {
    "CellPhase": CellPhase,
    "SizingPolicy": SizingPolicy,
    "BuyExecutionStatus": BuyExecutionStatus,
    "BuyAttemptStatus": BuyAttemptStatus,
    "SellAttemptStatus": SellAttemptStatus,
    "SellTradeIdentityCoverage": SellTradeIdentityCoverage,
    "SellTradePagination": SellTradePagination,
    "SellCollectionStopReason": SellCollectionStopReason,
    "SellFindingKind": SellFindingKind,
    "SellReconciliationCode": SellReconciliationCode,
    "OfflineSellSource": OfflineSellSource,
    "OfflineIssueCode": OfflineIssueCode,
    "ReceiptClassification": ReceiptClassification,
    "Side": Side,
    "OrderType": OrderType,
    "OrderStatus": OrderStatus,
    "LiquidityRole": LiquidityRole,
}

_MAX_TEXT = 16_000_000
_MAX_DEPTH = 96
_MAX_NODES = 500_000


def _failure(code: PersistenceErrorCode, detail: str) -> PersistenceError:
    return PersistenceError(code, detail)


def _encode(value: object, depth: int, budget: list[int]) -> object:
    budget[0] += 1
    if depth > _MAX_DEPTH or budget[0] > _MAX_NODES:
        raise _failure(PersistenceErrorCode.LIMIT_EXCEEDED, "grafo excede limite do codec")
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is Decimal:
        if not value.is_finite():
            raise _failure(PersistenceErrorCode.INVALID_DECIMAL, "Decimal não finito")
        decimal_tuple = value.as_tuple()
        if len(decimal_tuple.digits) > 4096:
            raise _failure(
                PersistenceErrorCode.LIMIT_EXCEEDED, "coeficiente excede limite do codec"
            )
        return {
            "decimal": [
                decimal_tuple.sign,
                "".join(map(str, decimal_tuple.digits)),
                decimal_tuple.exponent,
            ]
        }
    if type(value) is tuple:
        return {"tuple": [_encode(item, depth + 1, budget) for item in value]}
    enum_type = _ENUMS.get(type(value).__name__)
    if enum_type is not None and type(value) is enum_type and isinstance(value, StrEnum):
        return {"enum": [enum_type.__name__, value.value]}
    contract = _CONTRACTS.get(type(value).__name__)
    if contract is None or type(value) is not contract[0]:
        raise _failure(PersistenceErrorCode.INVALID_STATE, "tipo fora do registry fechado")
    cls, names = contract
    if tuple(f.name for f in fields(cls)) != names:
        raise _failure(PersistenceErrorCode.UNKNOWN_SCHEMA, "campos Python mudaram sem novo schema")
    return {
        "type": cls.__name__,
        "fields": {name: _encode(getattr(value, name), depth + 1, budget) for name in names},
    }


def _decode(value: object, depth: int, budget: list[int]) -> object:
    budget[0] += 1
    if depth > _MAX_DEPTH or budget[0] > _MAX_NODES:
        raise _failure(PersistenceErrorCode.LIMIT_EXCEEDED, "grafo excede limite do codec")
    if value is None or type(value) in (str, int, bool):
        return value
    if not isinstance(value, dict):
        raise _failure(PersistenceErrorCode.CORRUPT_JSON, "tag explícita requerida")
    if set(value) == {"decimal"}:
        parts = value["decimal"]
        if (
            not isinstance(parts, list)
            or len(parts) != 3
            or type(parts[0]) is not int
            or parts[0] not in (0, 1)
            or not isinstance(parts[1], str)
            or not 1 <= len(parts[1]) <= 4096
            or not parts[1].isascii()
            or not parts[1].isdecimal()
            or type(parts[2]) is not int
        ):
            raise _failure(PersistenceErrorCode.INVALID_DECIMAL, "tupla Decimal inválida")
        try:
            result = Decimal((parts[0], tuple(int(digit) for digit in parts[1]), parts[2]))
        except (ValueError, DecimalException, OverflowError) as exc:
            raise _failure(
                PersistenceErrorCode.INVALID_DECIMAL, "tupla Decimal não representável"
            ) from exc
        if not result.is_finite() or result.as_tuple().digits != tuple(int(d) for d in parts[1]):
            raise _failure(PersistenceErrorCode.INVALID_DECIMAL, "coeficiente não canônico")
        return result
    if set(value) == {"tuple"}:
        items = value["tuple"]
        if not isinstance(items, list):
            raise _failure(PersistenceErrorCode.CORRUPT_JSON, "tuple exige array")
        return tuple(_decode(item, depth + 1, budget) for item in items)
    if set(value) == {"enum"}:
        items = value["enum"]
        if not isinstance(items, list) or len(items) != 2 or not all(type(i) is str for i in items):
            raise _failure(PersistenceErrorCode.CORRUPT_JSON, "enum inválido")
        enum_type = _ENUMS.get(items[0])
        if enum_type is None:
            raise _failure(PersistenceErrorCode.UNKNOWN_SCHEMA, "enum desconhecido")
        try:
            return enum_type(items[1])
        except ValueError as exc:
            raise _failure(PersistenceErrorCode.INVALID_STATE, "membro enum desconhecido") from exc
    if set(value) != {"type", "fields"} or type(value["type"]) is not str:
        raise _failure(PersistenceErrorCode.CORRUPT_JSON, "objeto contratual inválido")
    contract = _CONTRACTS.get(value["type"])
    if contract is None:
        raise _failure(PersistenceErrorCode.UNKNOWN_SCHEMA, "contrato desconhecido")
    cls, names = contract
    members = value["fields"]
    if not isinstance(members, dict) or set(members) != set(names):
        raise _failure(PersistenceErrorCode.INVALID_STATE, "grafo parcial/campos desconhecidos")
    kwargs = {name: _decode(members[name], depth + 1, budget) for name in names}
    try:
        return cls(**kwargs)
    except PersistenceError:
        raise
    except (
        DomainError,
        TypeError,
        AttributeError,
        ValueError,
        DecimalException,
        IndexError,
    ) as exc:
        raise _failure(PersistenceErrorCode.INVALID_STATE, "contrato financeiro inválido") from exc


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("chave JSON repetida")
        result[name] = value
    return result


def _non_json_number(_: str) -> object:
    raise ValueError("float/NaN/Infinity proibido no formato persistente")


def encode_contract(value: object) -> str:
    """Registry literal; nenhum tipo escolhido por dado pode importar/executar código externo."""
    try:
        text = json.dumps(
            {"schema": 1, "value": _encode(value, 0, [0])},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except PersistenceError:
        raise
    except (ValueError, TypeError, RecursionError, AttributeError) as exc:
        raise _failure(PersistenceErrorCode.INVALID_STATE, "grafo não serializável") from exc
    if len(text) > _MAX_TEXT:
        raise _failure(PersistenceErrorCode.LIMIT_EXCEEDED, "texto excede limite do codec")
    return text


def decode_contract(text: str) -> object:
    """Reconstrói fontes conhecidas pelos construtores reais, sem defaults financeiros."""
    if type(text) is not str or len(text) > _MAX_TEXT:
        raise _failure(PersistenceErrorCode.LIMIT_EXCEEDED, "texto fora do limite do codec")
    try:
        data: object = json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_float=_non_json_number,
            parse_constant=_non_json_number,
        )
    except (ValueError, TypeError, RecursionError) as exc:
        raise _failure(PersistenceErrorCode.CORRUPT_JSON, "JSON persistido inválido") from exc
    if not isinstance(data, dict) or set(data) != {"schema", "value"}:
        raise _failure(PersistenceErrorCode.CORRUPT_JSON, "envelope inválido")
    if type(data["schema"]) is not int or data["schema"] != 1:
        raise _failure(PersistenceErrorCode.UNKNOWN_SCHEMA, "versão de codec desconhecida")
    return _decode(data["value"], 0, [0])


def revalidate_contract[T](value: T, expected: type[T]) -> T:
    """Round-trip revalida profundamente, inclusive objetos frozen adulterados."""
    text = encode_contract(value)
    result = decode_contract(text)
    if type(result) is not expected:
        raise _failure(PersistenceErrorCode.INVALID_STATE, "contrato recuperado de outro tipo")
    if encode_contract(result) != text:
        raise _failure(PersistenceErrorCode.INVALID_STATE, "round-trip alterou representação")
    return result
