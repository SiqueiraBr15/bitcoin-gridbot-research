"""Enums de ordem. Valores espelham a nomenclatura da Binance Spot, sem depender dela."""

from __future__ import annotations

from enum import StrEnum

from gridbot.domain.errors import DomainError


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def opposite(self) -> Side:
        return Side.SELL if self is Side.BUY else Side.BUY


class OrderType(StrEnum):
    LIMIT = "LIMIT"
    LIMIT_MAKER = "LIMIT_MAKER"
    MARKET = "MARKET"

    @property
    def requires_price(self) -> bool:
        return self is not OrderType.MARKET


class LiquidityRole(StrEnum):
    """Papel de liquidez de uma execução, conhecido só no momento do fill.

    Uma ordem LIMIT NÃO implica MAKER: se cruzar o book ao entrar, executa como TAKER.
    Quem determina o papel é a execução (simulador/exchange), nunca a estratégia (ADR-009).
    """

    MAKER = "MAKER"
    TAKER = "TAKER"


class OrderStatus(StrEnum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    EXPIRED_IN_MATCH = "EXPIRED_IN_MATCH"

    @property
    def is_terminal(self) -> bool:
        return not _TRANSITIONS[self]

    @property
    def is_open(self) -> bool:
        return self in (OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED)

    def can_transition_to(self, target: OrderStatus) -> bool:
        return target in _TRANSITIONS[self]


_CLOSING = frozenset(
    {
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
        OrderStatus.EXPIRED,
        OrderStatus.EXPIRED_IN_MATCH,
    }
)

_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.NEW: _CLOSING | {OrderStatus.PARTIALLY_FILLED},
    OrderStatus.PARTIALLY_FILLED: _CLOSING | {OrderStatus.PARTIALLY_FILLED},
    OrderStatus.FILLED: frozenset(),
    OrderStatus.CANCELED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
    OrderStatus.EXPIRED: frozenset(),
    OrderStatus.EXPIRED_IN_MATCH: frozenset(),
}


def parse_enum[E: StrEnum](enum_cls: type[E], raw: object) -> E:
    """Converte texto exato (case-sensitive) em membro do enum; rejeita o resto."""
    if not isinstance(raw, str):
        raise DomainError(f"{enum_cls.__name__}: esperado str, recebido {type(raw).__name__}")
    try:
        return enum_cls(raw)
    except ValueError:
        allowed = ", ".join(m.value for m in enum_cls)
        raise DomainError(f"{enum_cls.__name__} inválido: {raw!r} (aceitos: {allowed})") from None
