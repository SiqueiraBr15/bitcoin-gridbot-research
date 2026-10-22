from __future__ import annotations

import pytest

from gridbot.domain import (
    BTC,
    BTCUSDT,
    USDT,
    Asset,
    Balance,
    ClientOrderId,
    DomainError,
    GridLevel,
    Price,
    Qty,
    SequentialIdGenerator,
    Symbol,
)

# ------------------------------------------------------------------ IDs


@pytest.mark.parametrize("value", ["gb-1", "A.b:c/d_e-f", "x" * 36])
def test_client_order_id_accepts_binance_charset(value: str) -> None:
    assert str(ClientOrderId(value)) == value


@pytest.mark.parametrize("value", ["", "x" * 37, "has space", "ação", "a#b"])
def test_client_order_id_rejects_invalid(value: str) -> None:
    with pytest.raises(DomainError):
        ClientOrderId(value)


def test_sequential_ids_are_deterministic_and_valid() -> None:
    first = SequentialIdGenerator("run42")
    second = SequentialIdGenerator("run42")
    ids_a = [first.next_id() for _ in range(5)]
    ids_b = [second.next_id() for _ in range(5)]
    assert ids_a == ids_b == ["run42-1", "run42-2", "run42-3", "run42-4", "run42-5"]
    assert all(ClientOrderId(i) for i in ids_a)
    assert len(set(ids_a)) == len(ids_a)


@pytest.mark.parametrize("prefix", ["", "bad-prefix", "x" * 25, "espaço"])
def test_sequential_ids_reject_bad_prefix(prefix: str) -> None:
    with pytest.raises(DomainError):
        SequentialIdGenerator(prefix)


def test_sequential_ids_fail_closed_when_exhausted() -> None:
    gen = SequentialIdGenerator("p" * 24, start=10**11)
    with pytest.raises(DomainError):
        gen.next_id()


# ------------------------------------------------------------------ Asset / Symbol


def test_symbol_name() -> None:
    assert BTCUSDT.name == "BTCUSDT"
    assert str(BTCUSDT) == "BTCUSDT"


@pytest.mark.parametrize("code", ["btc", "B", "BTC-USDT", ""])
def test_invalid_asset(code: str) -> None:
    with pytest.raises(DomainError):
        Asset(code)


def test_symbol_rejects_same_base_and_quote() -> None:
    with pytest.raises(DomainError):
        Symbol(BTC, BTC)


# ------------------------------------------------------------------ GridLevel / Balance


def test_grid_level_validation_and_order() -> None:
    low, high = GridLevel(0, Price.parse("50000")), GridLevel(1, Price.parse("51000"))
    assert low < high
    for bad in (-1, True):
        with pytest.raises(DomainError):
            GridLevel(bad, Price.parse("1"))


def test_balance_total() -> None:
    bal = Balance(USDT, free=Qty.parse("100.5"), locked=Qty.parse("49.5"))
    assert bal.total == Qty.parse("150")
