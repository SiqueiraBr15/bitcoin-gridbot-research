"""Value objects financeiros: Price, Qty e Money. Sempre ``Decimal`` (ADR-002)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from gridbot.domain.assets import Asset
from gridbot.domain.decimals import DecimalInput, financial, require_finite, to_decimal
from gridbot.domain.errors import DomainError


@dataclass(frozen=True, slots=True, order=True)
class Price:
    """Preço estritamente positivo."""

    value: Decimal

    def __post_init__(self) -> None:
        value = require_finite(self.value, field="Price")
        if value <= 0:
            raise DomainError(f"Price deve ser > 0 (recebido {value})")

    @classmethod
    def parse(cls, raw: DecimalInput) -> Price:
        return cls(to_decimal(raw, field="Price"))

    def notional(self, qty: Qty) -> Decimal:
        """Valor em moeda de cotação de ``qty`` a este preço (exato, sem arredondamento)."""
        if not isinstance(qty, Qty):
            raise TypeError("notional exige Qty")
        with financial():
            return self.value * qty.value

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True, order=True)
class Qty:
    """Quantidade não negativa de um ativo."""

    value: Decimal

    def __post_init__(self) -> None:
        value = require_finite(self.value, field="Qty")
        if value < 0:
            raise DomainError(f"Qty não pode ser negativa (recebido {value})")

    @classmethod
    def parse(cls, raw: DecimalInput) -> Qty:
        return cls(to_decimal(raw, field="Qty"))

    @classmethod
    def zero(cls) -> Qty:
        return cls(Decimal(0))

    @property
    def is_zero(self) -> bool:
        return self.value == 0

    def __add__(self, other: Qty) -> Qty:
        if not isinstance(other, Qty):
            return NotImplemented
        with financial():
            return Qty(self.value + other.value)

    def __sub__(self, other: Qty) -> Qty:
        """Subtração; resultado negativo viola o invariante e levanta ``DomainError``."""
        if not isinstance(other, Qty):
            return NotImplemented
        with financial():
            return Qty(self.value - other.value)

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class Money:
    """Quantia (com sinal) de um ativo; usada para saldos, taxas e PnL."""

    amount: Decimal
    asset: Asset

    def __post_init__(self) -> None:
        require_finite(self.amount, field="Money.amount")
        if not isinstance(self.asset, Asset):
            raise TypeError("Money.asset deve ser Asset")

    @classmethod
    def parse(cls, raw: DecimalInput, asset: Asset) -> Money:
        return cls(to_decimal(raw, field="Money.amount"), asset)

    @classmethod
    def zero(cls, asset: Asset) -> Money:
        return cls(Decimal(0), asset)

    @property
    def is_negative(self) -> bool:
        return self.amount < 0

    def _same_asset(self, other: Money) -> None:
        if self.asset != other.asset:
            raise DomainError(f"Ativos diferentes: {self.asset} vs {other.asset}")

    def __add__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        self._same_asset(other)
        with financial():
            return Money(self.amount + other.amount, self.asset)

    def __sub__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        self._same_asset(other)
        with financial():
            return Money(self.amount - other.amount, self.asset)

    def __neg__(self) -> Money:
        """Inverte o sinal exatamente, sem aritmética ou arredondamento por contexto."""
        return Money(self.amount.copy_negate(), self.asset)

    def __str__(self) -> str:
        return f"{self.amount} {self.asset}"
