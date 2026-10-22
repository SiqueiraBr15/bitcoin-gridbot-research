"""ACL offline A17.2. JSON fornecido, sem I/O; raw é preservado antes de projetar.

Scope e metadados são declarações do chamador, não autenticação. Campos novos
continuam no JSON literal e são enumerados. Nenhum financeiro ausente vira zero.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from decimal import DecimalException
from enum import StrEnum
from typing import overload

from gridbot.application.sell_evidence import (
    CollectedSellTrade,
    ObservedSellOrderReport,
    SellOrderIdentity,
    SellTradeIdentityCoverage,
    _nested,
    _ref,
    _typed,
)
from gridbot.domain.assets import Asset
from gridbot.domain.enums import LiquidityRole, OrderStatus, OrderType, Side
from gridbot.domain.errors import DomainError
from gridbot.domain.values import Money, Price, Qty


class OfflineSellSource(StrEnum):
    ORDER = "ORDER"
    MY_TRADES_PAGE = "MY_TRADES_PAGE"
    EXECUTION_REPORT = "EXECUTION_REPORT"


@dataclass(frozen=True, slots=True)
class RawSellObservation:
    source_ref: str
    kind: OfflineSellSource
    scope: SellOrderIdentity
    payload: str = field(repr=False)
    collection_ref: str | None = None
    cursor_from: str | None = None
    next_cursor: str | None = None
    requested_limit: int | None = None

    def __post_init__(self) -> None:
        _ref(self.source_ref)
        _typed(self.kind, OfflineSellSource)
        _nested(self.scope, SellOrderIdentity)
        _typed(self.payload, str)
        for ref in (self.collection_ref, self.cursor_from, self.next_cursor):
            if ref is not None:
                _ref(ref)
        if self.requested_limit is not None and (
            type(self.requested_limit) is not int or self.requested_limit <= 0
        ):
            raise DomainError("requested_limit exige inteiro positivo")


class OfflineIssueCode(StrEnum):
    MISSING = "MISSING"
    NULL = "NULL"
    MALFORMED = "MALFORMED"
    UNSUPPORTED = "UNSUPPORTED"
    FINANCIAL_PRECISION_ERROR = "FINANCIAL_PRECISION_ERROR"
    SOURCE_ERROR = "SOURCE_ERROR"
    IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
    RAW_CONFLICT = "RAW_CONFLICT"
    TRADE_CONFLICT = "TRADE_CONFLICT"
    FINANCIAL_QUARANTINE = "FINANCIAL_QUARANTINE"
    ROOT_UNAVAILABLE = "ROOT_UNAVAILABLE"
    SOURCE_NOT_SELECTED = "SOURCE_NOT_SELECTED"
    UNASSESSED_SOURCE = "UNASSESSED_SOURCE"


@dataclass(frozen=True, slots=True)
class OfflineSellIssue:
    code: OfflineIssueCode
    source_ref: str
    field: str
    detail: str

    def __post_init__(self) -> None:
        _typed(self.code, OfflineIssueCode)
        for value in (self.source_ref, self.field, self.detail):
            _typed(value, str)


@dataclass(frozen=True, slots=True)
class NormalizedSellObservation:
    raw: RawSellObservation
    report: ObservedSellOrderReport | None
    trades: tuple[CollectedSellTrade, ...]
    issues: tuple[OfflineSellIssue, ...]
    unknown_fields: tuple[str, ...]
    non_trade: bool = False

    def __post_init__(self) -> None:
        replace(self.raw)
        if self.report is not None:
            _nested(self.report, ObservedSellOrderReport)
        for values, expected in (
            (self.trades, CollectedSellTrade),
            (self.issues, OfflineSellIssue),
            (self.unknown_fields, str),
        ):
            _typed(values, tuple)
            for value in values:
                _typed(value, expected)
                if not isinstance(value, str):
                    replace(value)
        if type(self.non_trade) is not bool:
            raise TypeError("non_trade exige bool")


@dataclass(frozen=True, slots=True)
class _JsonNumber:
    lexical: str


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("chave JSON repetida")
        result[key] = value
    return result


def _constant(_: str) -> object:
    raise ValueError("constante não JSON")


class _Reader:
    def __init__(self, raw: RawSellObservation) -> None:
        self.raw = raw
        self.issues: list[OfflineSellIssue] = []
        self.unknown: list[str] = []

    def issue(self, code: OfflineIssueCode, name: str, detail: str) -> None:
        self.issues.append(OfflineSellIssue(code, self.raw.source_ref, name, detail))

    def value(self, data: dict[str, object], name: str, prefix: str = "") -> object:
        if name not in data:
            self.issue(OfflineIssueCode.MISSING, prefix + name, "campo ausente")
        elif data[name] is None:
            self.issue(OfflineIssueCode.NULL, prefix + name, "null explícito")
        return data.get(name)

    def text(self, data: dict[str, object], name: str, prefix: str = "") -> str | None:
        value = self.value(data, name, prefix)
        if value is None:
            return None
        if not isinstance(value, str):
            self.issue(OfflineIssueCode.MALFORMED, prefix + name, "string obrigatória")
            return None
        return value

    def native_id(self, data: dict[str, object], name: str, prefix: str = "") -> str | None:
        value = self.value(data, name, prefix)
        if value is None:
            return None
        text = str(value) if type(value) is int else value
        if not isinstance(text, str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,19})", text):
            self.issue(OfflineIssueCode.MALFORMED, prefix + name, "ID nativo não negativo canônico")
            return None
        return text

    @overload
    def finance(
        self,
        data: dict[str, object],
        name: str,
        expected: type[Qty],
        asset: Asset | None = None,
        prefix: str = "",
    ) -> Qty | None: ...

    @overload
    def finance(
        self,
        data: dict[str, object],
        name: str,
        expected: type[Price],
        asset: Asset | None = None,
        prefix: str = "",
    ) -> Price | None: ...

    @overload
    def finance(
        self,
        data: dict[str, object],
        name: str,
        expected: type[Money],
        asset: Asset | None = None,
        prefix: str = "",
    ) -> Money | None: ...

    def finance(
        self,
        data: dict[str, object],
        name: str,
        expected: type[Qty] | type[Price] | type[Money],
        asset: Asset | None = None,
        prefix: str = "",
    ) -> Qty | Price | Money | None:
        value = self.text(data, name, prefix)
        if value is None:
            return None
        # Gramática wire restrita; Decimal aceita NaN/underscores/exponentes que
        # esta ACL não aceita. O raw nunca é corrigido para satisfazer a gramática.
        if len(value) > 128 or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
            self.issue(OfflineIssueCode.MALFORMED, prefix + name, "decimal wire não negativo")
            return None
        try:
            if expected is Money:
                if asset is None:
                    return None
                return Money.parse(value, asset)
            elif expected is Qty:
                return Qty.parse(value)
            else:
                return Price.parse(value)
        except (DomainError, DecimalException) as exc:
            code = OfflineIssueCode.MALFORMED
            if isinstance(exc, DecimalException):
                code = OfflineIssueCode.FINANCIAL_PRECISION_ERROR
            self.issue(code, prefix + name, type(exc).__name__)
            return None

    def enum[T: StrEnum](
        self,
        data: dict[str, object],
        name: str,
        expected: type[T],
        prefix: str = "",
    ) -> T | None:
        value = self.text(data, name, prefix)
        if value is None:
            return None
        try:
            return expected(value)
        except ValueError:
            self.issue(OfflineIssueCode.UNSUPPORTED, prefix + name, "enum fora do contrato")
            return None

    def identity(
        self,
        data: dict[str, object],
        event: bool,
        prefix: str = "",
    ) -> SellOrderIdentity | None:
        symbol = self.text(data, "s" if event else "symbol", prefix)
        order = self.native_id(data, "i" if event else "orderId", prefix)
        client_name = "c" if event else "clientOrderId"
        # myTrades não traz clientOrderId. Não completar pela identidade esperada.
        client = self.text(data, client_name, prefix) if client_name in data else None
        if symbol is None or order is None:
            return None
        if symbol != str(self.raw.scope.symbol):
            self.issue(
                OfflineIssueCode.IDENTITY_CONFLICT, prefix + "symbol", "símbolo fora do scope"
            )
            return None
        try:
            return replace(self.raw.scope, order_ref=order, client_order_ref=client)
        except DomainError as exc:
            self.issue(OfflineIssueCode.MALFORMED, prefix + "identity", type(exc).__name__)
            return None

    def unknowns(self, data: dict[str, object], known: set[str], prefix: str = "") -> None:
        self.unknown.extend(prefix + name for name in sorted(data.keys() - known))

    def order(self, data: dict[str, object], event: bool) -> ObservedSellOrderReport | None:
        names = (
            ("X", "q", "z", "Z", "p", "S", "o")
            if event
            else (
                "status",
                "origQty",
                "executedQty",
                "cummulativeQuoteQty",
                "price",
                "side",
                "type",
            )
        )
        ident = self.identity(data, event)
        status = self.enum(data, names[0], OrderStatus)
        qty = self.finance(data, names[1], Qty)
        executed = self.finance(data, names[2], Qty)
        quote = self.finance(data, names[3], Money, self.raw.scope.symbol.quote)
        price = self.finance(data, names[4], Price)
        side = self.enum(data, names[5], Side)
        order_type = self.enum(data, names[6], OrderType)
        if ident is None or side is None or order_type is None:
            return None
        return ObservedSellOrderReport(
            ident,
            status,
            qty,
            executed,
            quote,
            price,
            side,
            order_type,
            self.raw.source_ref,
            self.raw.collection_ref,
        )

    def trade(
        self,
        data: dict[str, object],
        event: bool,
        prefix: str = "",
    ) -> CollectedSellTrade | None:
        ident = self.identity(data, event, prefix)
        names = (
            ("t", "L", "l", "Y", "n", "N", "m")
            if event
            else ("id", "price", "qty", "quoteQty", "commission", "commissionAsset", "isMaker")
        )
        trade_id = self.native_id(data, names[0], prefix)
        price = self.finance(data, names[1], Price, prefix=prefix)
        qty = self.finance(data, names[2], Qty, prefix=prefix)
        quote = self.finance(data, names[3], Money, self.raw.scope.symbol.quote, prefix)
        asset_name = self.text(data, names[5], prefix)
        asset = None
        if asset_name is not None:
            try:
                asset = Asset(asset_name)
            except DomainError:
                self.issue(OfflineIssueCode.MALFORMED, prefix + names[5], "ativo inválido")
        fee = self.finance(data, names[4], Money, asset, prefix)
        maker = data.get(names[6])
        liquidity = None
        if names[6] in data:
            if type(maker) is bool:
                liquidity = LiquidityRole.MAKER if maker else LiquidityRole.TAKER
            else:
                self.issue(OfflineIssueCode.MALFORMED, prefix + names[6], "maker exige bool")
        if event:
            side = self.enum(data, "S", Side, prefix)
        else:
            buyer = self.value(data, "isBuyer", prefix)
            side = (Side.BUY if buyer else Side.SELL) if type(buyer) is bool else None
            if buyer is not None and side is None:
                self.issue(OfflineIssueCode.MALFORMED, prefix + "isBuyer", "buyer exige bool")
        if ident is None or trade_id is None or side is None:
            return None
        coverage = SellTradeIdentityCoverage.FULL_DECLARED_IDENTITY
        if not event and ident.client_order_ref is None:
            coverage = SellTradeIdentityCoverage.ORDER_ID_WITHOUT_CLIENT_ID
        return CollectedSellTrade(
            ident, trade_id, price, qty, quote, fee, side, liquidity, coverage
        )


_ORDER_FIELDS = set(
    [
        "symbol",
        "orderId",
        "clientOrderId",
        "status",
        "origQty",
        "executedQty",
        "cummulativeQuoteQty",
        "price",
        "side",
        "type",
    ]
)
_TRADE_FIELDS = set(
    [
        "symbol",
        "orderId",
        "id",
        "price",
        "qty",
        "quoteQty",
        "commission",
        "commissionAsset",
        "isBuyer",
        "isMaker",
    ]
)
_EVENT_FIELDS = set(
    [
        "e",
        "s",
        "c",
        "i",
        "X",
        "q",
        "z",
        "Z",
        "p",
        "S",
        "o",
        "x",
        "t",
        "L",
        "l",
        "Y",
        "n",
        "N",
        "m",
        "I",
    ]
)


def normalize_sell_observation(raw: RawSellObservation) -> NormalizedSellObservation:
    replace(raw)
    reader = _Reader(raw)
    report = None
    trades: list[CollectedSellTrade] = []
    non_trade = False
    try:
        if len(raw.payload) > 2_000_000:
            raise ValueError("payload excede limite offline")
        data: object = json.loads(
            raw.payload,
            object_pairs_hook=_pairs,
            parse_float=_JsonNumber,
            parse_constant=_constant,
        )
        if isinstance(data, dict) and "code" in data:
            reader.issue(
                OfflineIssueCode.SOURCE_ERROR, "response", "resultado externo desconhecido"
            )
        elif raw.kind is OfflineSellSource.MY_TRADES_PAGE:
            if not isinstance(data, list):
                raise ValueError("página exige array JSON")
            for index, item in enumerate(data):
                prefix = f"row:{index}."
                if not isinstance(item, dict):
                    reader.issue(OfflineIssueCode.MALFORMED, prefix, "trade exige objeto")
                    continue
                reader.unknowns(item, _TRADE_FIELDS, prefix)
                trade = reader.trade(item, False, prefix)
                if trade is not None:
                    trades.append(trade)
        elif isinstance(data, dict):
            event = raw.kind is OfflineSellSource.EXECUTION_REPORT
            if event and "event" in data:
                reader.unknowns(data, {"subscriptionId", "event"}, "wrapper.")
                data = data["event"]
                if not isinstance(data, dict):
                    raise ValueError("event exige objeto")
            reader.unknowns(data, _EVENT_FIELDS if event else _ORDER_FIELDS)
            if event and data.get("e") != "executionReport":
                reader.issue(OfflineIssueCode.UNSUPPORTED, "e", "evento não executionReport")
            else:
                report = reader.order(data, event)
                if event:
                    execution_type = reader.text(data, "x")
                    if execution_type == "TRADE":
                        trade = reader.trade(data, True)
                        if trade is not None:
                            trades.append(trade)
                    elif execution_type in {
                        "NEW",
                        "CANCELED",
                        "REPLACED",
                        "REJECTED",
                        "EXPIRED",
                        "TRADE_PREVENTION",
                    }:
                        non_trade = True
                    elif execution_type is not None:
                        reader.issue(
                            OfflineIssueCode.UNSUPPORTED, "x", "tipo execução não suportado"
                        )
        else:
            raise ValueError("resposta exige objeto JSON")
    except (ValueError, TypeError, RecursionError) as exc:
        reader.issue(OfflineIssueCode.MALFORMED, "payload", type(exc).__name__)
    except (DomainError, DecimalException) as exc:
        code = OfflineIssueCode.MALFORMED
        if (
            isinstance(exc, DecimalException)
            or getattr(exc, "code", None) == "FINANCIAL_PRECISION_ERROR"
        ):
            code = OfflineIssueCode.FINANCIAL_PRECISION_ERROR
        reader.issue(code, "projection", type(exc).__name__)
    return NormalizedSellObservation(
        raw, report, tuple(trades), tuple(reader.issues), tuple(reader.unknown), non_trade
    )
