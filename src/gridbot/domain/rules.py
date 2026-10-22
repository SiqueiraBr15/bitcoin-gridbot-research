"""Regras de mercado Spot independentes de exchange (ADR-009).

Respondem se um preço/quantidade hipotéticos poderiam existir num mercado. Não conhecem
JSON, REST nem nomes de filtros de nenhuma exchange: a tradução exchange -> ``MarketRules``
pertence ao adapter da exchange.

Convenções:
- alinhamento = múltiplo exato de ``tick_size``/``step_size`` (sem epsilon);
- todos os limites (min e max) são INCLUSIVOS;
- limites opcionais (``None``) não são verificados;
- verificar nunca altera valores; quantizar (floor/ceil) é sempre explícito;
- ``check`` reporta TODAS as violações, em ordem fixa (preço, quantidade, notional).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from gridbot.domain.assets import Symbol
from gridbot.domain.decimals import DecimalInput, require_finite, to_decimal
from gridbot.domain.errors import DomainError, InvalidMarketRulesError, MarketRuleViolationError
from gridbot.domain.quantization import ceil_to_increment, floor_to_increment, is_multiple_of
from gridbot.domain.values import Money, Price, Qty

_ZERO = Decimal(0)


class RuleViolationCode(StrEnum):
    PRICE_NOT_ALIGNED = "PRICE_NOT_ALIGNED"
    PRICE_BELOW_MIN = "PRICE_BELOW_MIN"
    PRICE_ABOVE_MAX = "PRICE_ABOVE_MAX"
    QTY_NOT_ALIGNED = "QTY_NOT_ALIGNED"
    QTY_BELOW_MIN = "QTY_BELOW_MIN"
    QTY_ABOVE_MAX = "QTY_ABOVE_MAX"
    NOTIONAL_BELOW_MIN = "NOTIONAL_BELOW_MIN"
    NOTIONAL_ABOVE_MAX = "NOTIONAL_ABOVE_MAX"


@dataclass(frozen=True, slots=True)
class RuleViolation:
    """Uma violação: valor verificado e a referência violada (incremento ou limite)."""

    code: RuleViolationCode
    actual: Decimal
    reference: Decimal

    def __str__(self) -> str:
        return f"{self.code}: {self.actual} (referência {self.reference})"


def _expect(value: object, expected: type, field: str) -> None:
    if not isinstance(value, expected):
        raise TypeError(f"{field}: esperado {expected.__name__}, recebido {type(value).__name__}")


def _expect_optional(value: object, expected: type, field: str) -> None:
    if value is not None:
        _expect(value, expected, field)


# ------------------------------------------------------------------ preço


@dataclass(frozen=True, slots=True)
class PriceRules:
    """Grade de preço: múltiplos de ``tick_size``; limites opcionais inclusivos."""

    tick_size: Price
    min_price: Price | None = None
    max_price: Price | None = None

    def __post_init__(self) -> None:
        _expect(self.tick_size, Price, "tick_size")
        _expect_optional(self.min_price, Price, "min_price")
        _expect_optional(self.max_price, Price, "max_price")
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.max_price < self.min_price
        ):
            raise InvalidMarketRulesError(
                f"max_price {self.max_price} < min_price {self.min_price}"
            )

    def is_aligned(self, price: Price) -> bool:
        return is_multiple_of(price.value, self.tick_size.value)

    def floor(self, price: Price) -> Price:
        """Maior preço da grade <= ``price``. Erro se o resultado for 0 (não é Price)."""
        floored = floor_to_increment(price.value, self.tick_size.value)
        if floored == _ZERO:
            raise DomainError(f"floor de {price} com tick {self.tick_size} resulta em 0")
        return Price(floored)

    def ceil(self, price: Price) -> Price:
        """Menor preço da grade >= ``price``."""
        return Price(ceil_to_increment(price.value, self.tick_size.value))

    def violations(self, price: Price) -> tuple[RuleViolation, ...]:
        _expect(price, Price, "price")
        found: list[RuleViolation] = []
        if not self.is_aligned(price):
            found.append(
                RuleViolation(
                    RuleViolationCode.PRICE_NOT_ALIGNED, price.value, self.tick_size.value
                )
            )
        if self.min_price is not None and price < self.min_price:
            found.append(
                RuleViolation(RuleViolationCode.PRICE_BELOW_MIN, price.value, self.min_price.value)
            )
        if self.max_price is not None and price > self.max_price:
            found.append(
                RuleViolation(RuleViolationCode.PRICE_ABOVE_MAX, price.value, self.max_price.value)
            )
        return tuple(found)


# ------------------------------------------------------------------ quantidade


@dataclass(frozen=True, slots=True)
class QuantityRules:
    """Grade de quantidade: múltiplos de ``step_size``; ``min_qty`` > 0 obrigatório.

    ``min_qty`` > 0 porque uma ordem Spot de quantidade zero não existe.
    """

    step_size: Qty
    min_qty: Qty
    max_qty: Qty | None = None

    def __post_init__(self) -> None:
        _expect(self.step_size, Qty, "step_size")
        _expect(self.min_qty, Qty, "min_qty")
        _expect_optional(self.max_qty, Qty, "max_qty")
        if self.step_size.is_zero:
            raise InvalidMarketRulesError("step_size deve ser > 0")
        if self.min_qty.is_zero:
            raise InvalidMarketRulesError("min_qty deve ser > 0 (ordem de quantidade 0 não existe)")
        if self.max_qty is not None and self.max_qty < self.min_qty:
            raise InvalidMarketRulesError(f"max_qty {self.max_qty} < min_qty {self.min_qty}")

    def is_aligned(self, qty: Qty) -> bool:
        return is_multiple_of(qty.value, self.step_size.value)

    def floor(self, qty: Qty) -> Qty:
        """Maior quantidade da grade <= ``qty`` (pode ser 0)."""
        return Qty(floor_to_increment(qty.value, self.step_size.value))

    def ceil(self, qty: Qty) -> Qty:
        """Menor quantidade da grade >= ``qty``."""
        return Qty(ceil_to_increment(qty.value, self.step_size.value))

    def violations(self, qty: Qty) -> tuple[RuleViolation, ...]:
        _expect(qty, Qty, "qty")
        found: list[RuleViolation] = []
        if not self.is_aligned(qty):
            found.append(
                RuleViolation(RuleViolationCode.QTY_NOT_ALIGNED, qty.value, self.step_size.value)
            )
        if qty < self.min_qty:
            found.append(
                RuleViolation(RuleViolationCode.QTY_BELOW_MIN, qty.value, self.min_qty.value)
            )
        if self.max_qty is not None and qty > self.max_qty:
            found.append(
                RuleViolation(RuleViolationCode.QTY_ABOVE_MAX, qty.value, self.max_qty.value)
            )
        return tuple(found)


# ------------------------------------------------------------------ notional


@dataclass(frozen=True, slots=True)
class NotionalRules:
    """Limites de notional (preço x quantidade) na moeda de cotação do mercado.

    Valores em ``Decimal`` sem ativo: o ativo é sempre o ``quote`` do ``Symbol`` das
    ``MarketRules`` que contêm estas regras (sem duplicar informação).
    """

    min_notional: Decimal | None = None
    max_notional: Decimal | None = None

    def __post_init__(self) -> None:
        if self.min_notional is not None:
            require_finite(self.min_notional, field="min_notional")
            if self.min_notional < _ZERO:
                raise InvalidMarketRulesError(f"min_notional {self.min_notional} < 0")
        if self.max_notional is not None:
            require_finite(self.max_notional, field="max_notional")
            if self.max_notional <= _ZERO:
                raise InvalidMarketRulesError(f"max_notional {self.max_notional} deve ser > 0")
        if (
            self.min_notional is not None
            and self.max_notional is not None
            and self.max_notional < self.min_notional
        ):
            raise InvalidMarketRulesError(
                f"max_notional {self.max_notional} < min_notional {self.min_notional}"
            )

    @classmethod
    def parse(
        cls, min_notional: DecimalInput | None = None, max_notional: DecimalInput | None = None
    ) -> NotionalRules:
        return cls(
            None if min_notional is None else to_decimal(min_notional, field="min_notional"),
            None if max_notional is None else to_decimal(max_notional, field="max_notional"),
        )

    def violations(self, notional: Decimal) -> tuple[RuleViolation, ...]:
        found: list[RuleViolation] = []
        if self.min_notional is not None and notional < self.min_notional:
            found.append(
                RuleViolation(RuleViolationCode.NOTIONAL_BELOW_MIN, notional, self.min_notional)
            )
        if self.max_notional is not None and notional > self.max_notional:
            found.append(
                RuleViolation(RuleViolationCode.NOTIONAL_ABOVE_MAX, notional, self.max_notional)
            )
        return tuple(found)


# ------------------------------------------------------------------ composição


@dataclass(frozen=True, slots=True)
class RuleCheck:
    """Resultado de verificar uma proposta. ``ok`` só se não houver nenhuma violação."""

    symbol: Symbol
    price: Price
    qty: Qty
    notional: Money
    violations: tuple[RuleViolation, ...]

    @property
    def ok(self) -> bool:
        return not self.violations

    @property
    def codes(self) -> tuple[RuleViolationCode, ...]:
        return tuple(v.code for v in self.violations)

    def raise_if_invalid(self) -> None:
        if self.violations:
            detail = "; ".join(str(v) for v in self.violations)
            raise MarketRuleViolationError(
                f"proposta {self.symbol} price={self.price} qty={self.qty} rejeitada: {detail}",
                self,
            )


@dataclass(frozen=True, slots=True)
class MarketRules:
    """Regras de um mercado Spot. Fees ficam fora (dependem da conta): ver ``FeeSchedule``."""

    symbol: Symbol
    price: PriceRules
    quantity: QuantityRules
    notional: NotionalRules = NotionalRules()

    def __post_init__(self) -> None:
        _expect(self.symbol, Symbol, "symbol")
        _expect(self.price, PriceRules, "price")
        _expect(self.quantity, QuantityRules, "quantity")
        _expect(self.notional, NotionalRules, "notional")

    def notional_of(self, price: Price, qty: Qty) -> Money:
        """``price * qty`` exato, na moeda de cotação do mercado."""
        return Money(price.notional(qty), self.symbol.quote)

    def check(self, symbol: Symbol, price: Price, qty: Qty) -> RuleCheck:
        """Verifica (sem alterar) uma proposta e devolve todas as violações encontradas.

        Proposta de outro mercado é erro de programação (``DomainError``), não violação.
        """
        _expect(symbol, Symbol, "symbol")
        if symbol != self.symbol:
            raise DomainError(f"regras de {self.symbol} não se aplicam a {symbol}")
        _expect(price, Price, "price")
        _expect(qty, Qty, "qty")
        notional = self.notional_of(price, qty)
        violations = (
            *self.price.violations(price),
            *self.quantity.violations(qty),
            *self.notional.violations(notional.amount),
        )
        return RuleCheck(symbol, price, qty, notional, violations)
