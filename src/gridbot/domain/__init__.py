"""Núcleo de domínio: tipos puros, sem I/O, sem relógio real, sem dependências externas."""

from gridbot.domain.assets import BTC, BTCUSDT, USDT, Asset, Symbol
from gridbot.domain.balances import Balance
from gridbot.domain.clock import Clock, ManualClock
from gridbot.domain.decimals import FINANCIAL_CONTEXT, financial, require_finite, to_decimal
from gridbot.domain.enums import LiquidityRole, OrderStatus, OrderType, Side, parse_enum
from gridbot.domain.errors import (
    CandleSequenceError,
    DomainError,
    DuplicateCandleError,
    FloatNotAllowedError,
    InvalidCandleError,
    InvalidMarketRulesError,
    InvalidTimeframeError,
    MarketRuleViolationError,
    OutOfOrderCandleError,
    OverlappingCandleError,
)
from gridbot.domain.fees import FeeSchedule
from gridbot.domain.grid import GridLevel
from gridbot.domain.ids import ClientOrderId, IdGenerator, SequentialIdGenerator
from gridbot.domain.market import Candle, CandleGap, CandleSeries, WindowCoverage
from gridbot.domain.orders import Fill, OrderIntent, OrderSnapshot
from gridbot.domain.quantization import ceil_to_increment, floor_to_increment, is_multiple_of
from gridbot.domain.rules import (
    MarketRules,
    NotionalRules,
    PriceRules,
    QuantityRules,
    RuleCheck,
    RuleViolation,
    RuleViolationCode,
)
from gridbot.domain.time import require_utc
from gridbot.domain.timeframe import Timeframe
from gridbot.domain.values import Money, Price, Qty

__all__ = [
    "BTC",
    "BTCUSDT",
    "FINANCIAL_CONTEXT",
    "USDT",
    "Asset",
    "Balance",
    "Candle",
    "CandleGap",
    "CandleSequenceError",
    "CandleSeries",
    "ClientOrderId",
    "Clock",
    "DomainError",
    "DuplicateCandleError",
    "FeeSchedule",
    "Fill",
    "FloatNotAllowedError",
    "GridLevel",
    "IdGenerator",
    "InvalidCandleError",
    "InvalidMarketRulesError",
    "InvalidTimeframeError",
    "LiquidityRole",
    "ManualClock",
    "MarketRuleViolationError",
    "MarketRules",
    "Money",
    "NotionalRules",
    "OrderIntent",
    "OrderSnapshot",
    "OrderStatus",
    "OrderType",
    "OutOfOrderCandleError",
    "OverlappingCandleError",
    "Price",
    "PriceRules",
    "Qty",
    "QuantityRules",
    "RuleCheck",
    "RuleViolation",
    "RuleViolationCode",
    "SequentialIdGenerator",
    "Side",
    "Symbol",
    "Timeframe",
    "WindowCoverage",
    "ceil_to_increment",
    "financial",
    "floor_to_increment",
    "is_multiple_of",
    "parse_enum",
    "require_finite",
    "require_utc",
    "to_decimal",
]
