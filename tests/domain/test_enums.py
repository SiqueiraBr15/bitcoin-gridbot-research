from __future__ import annotations

import itertools

import pytest

from gridbot.domain import DomainError, OrderStatus, OrderType, Side, parse_enum

TERMINAL = {
    OrderStatus.FILLED,
    OrderStatus.CANCELED,
    OrderStatus.REJECTED,
    OrderStatus.EXPIRED,
    OrderStatus.EXPIRED_IN_MATCH,
}


@pytest.mark.parametrize(
    ("enum_cls", "raw", "expected"),
    [
        (Side, "BUY", Side.BUY),
        (Side, "SELL", Side.SELL),
        (OrderType, "LIMIT_MAKER", OrderType.LIMIT_MAKER),
        (OrderStatus, "PARTIALLY_FILLED", OrderStatus.PARTIALLY_FILLED),
        (OrderStatus, "EXPIRED_IN_MATCH", OrderStatus.EXPIRED_IN_MATCH),
    ],
)
def test_parse_enum_accepts_exact_values(
    enum_cls: type[Side | OrderType | OrderStatus], raw: str, expected: object
) -> None:
    assert parse_enum(enum_cls, raw) is expected


@pytest.mark.parametrize(
    ("enum_cls", "raw"),
    [
        (Side, "buy"),
        (Side, "HOLD"),
        (OrderType, "STOP_LOSS"),
        (OrderStatus, "PENDING"),
        (OrderStatus, ""),
        (Side, None),
        (Side, 1),
    ],
)
def test_parse_enum_rejects_unknown_values(
    enum_cls: type[Side | OrderType | OrderStatus], raw: object
) -> None:
    with pytest.raises(DomainError):
        parse_enum(enum_cls, raw)


def test_side_opposite() -> None:
    assert Side.BUY.opposite is Side.SELL
    assert Side.SELL.opposite is Side.BUY


def test_order_type_price_requirement() -> None:
    assert OrderType.LIMIT.requires_price
    assert OrderType.LIMIT_MAKER.requires_price
    assert not OrderType.MARKET.requires_price


def test_terminal_and_open_status_sets() -> None:
    assert {s for s in OrderStatus if s.is_terminal} == TERMINAL
    assert {s for s in OrderStatus if s.is_open} == {
        OrderStatus.NEW,
        OrderStatus.PARTIALLY_FILLED,
    }


@pytest.mark.parametrize(
    ("source", "target"), list(itertools.product(sorted(TERMINAL), list(OrderStatus)))
)
def test_terminal_status_never_transitions(source: OrderStatus, target: OrderStatus) -> None:
    assert not source.can_transition_to(target)


def test_open_status_transitions() -> None:
    new, partial = OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED
    assert new.can_transition_to(partial)
    assert new.can_transition_to(OrderStatus.FILLED)
    assert new.can_transition_to(OrderStatus.CANCELED)
    assert not new.can_transition_to(new)
    assert not new.can_transition_to(OrderStatus.REJECTED)  # rejeição só antes de aceitar
    assert partial.can_transition_to(partial)  # novos fills parciais
    assert not partial.can_transition_to(new)
