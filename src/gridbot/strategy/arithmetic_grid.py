"""Geometria pura do grid aritmético (ADR-010).

Responde apenas: dado um mercado, limites e número de INTERVALOS, quais são exatamente os
níveis de preço. Não decide BUY/SELL, quantidade, capital, ordens nem execução.

Semântica:
- ``interval_count`` = número de INTERVALOS; N intervalos geram N + 1 níveis;
- índice 0 = ``lower_price``; índice N = ``upper_price`` (limites inclusivos);
- geração exata em unidades inteiras de tick: nenhum arredondamento, nenhum "quase
  uniforme", nenhum ajuste do último nível;
- os limites precisam já estar alinhados ao tick (não são quantizados aqui) e a distância em
  ticks precisa ser divisível por ``interval_count``; caso contrário, o grid é rejeitado.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise

from gridbot.domain.assets import Symbol
from gridbot.domain.decimals import financial
from gridbot.domain.errors import DomainError, FloatNotAllowedError
from gridbot.domain.grid import GridLevel
from gridbot.domain.quantization import is_multiple_of
from gridbot.domain.rules import MarketRules
from gridbot.domain.values import Price


class GridErrorCode(StrEnum):
    INVALID_INTERVAL_COUNT = "INVALID_INTERVAL_COUNT"
    LOWER_NOT_BELOW_UPPER = "LOWER_NOT_BELOW_UPPER"
    SYMBOL_MISMATCH = "SYMBOL_MISMATCH"
    LOWER_PRICE_NOT_ALIGNED = "LOWER_PRICE_NOT_ALIGNED"
    UPPER_PRICE_NOT_ALIGNED = "UPPER_PRICE_NOT_ALIGNED"
    LOWER_PRICE_OUT_OF_RANGE = "LOWER_PRICE_OUT_OF_RANGE"
    UPPER_PRICE_OUT_OF_RANGE = "UPPER_PRICE_OUT_OF_RANGE"
    GRID_SPACING_NOT_REPRESENTABLE = "GRID_SPACING_NOT_REPRESENTABLE"
    PLAN_INVARIANT_VIOLATED = "PLAN_INVARIANT_VIOLATED"


class GridError(DomainError):
    """Configuração de grid inválida; ``code`` identifica o motivo."""

    def __init__(self, code: GridErrorCode, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def _expect(value: object, expected: type, field: str) -> None:
    if isinstance(value, float):
        raise FloatNotAllowedError(field)
    if not isinstance(value, expected):
        raise TypeError(f"{field}: esperado {expected.__name__}, recebido {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class ArithmeticGridSpec:
    """Parâmetros geométricos do grid. Sem quantidade, capital, fees ou preço atual."""

    symbol: Symbol
    lower_price: Price
    upper_price: Price
    interval_count: int

    def __post_init__(self) -> None:
        _expect(self.symbol, Symbol, "symbol")
        _expect(self.lower_price, Price, "lower_price")
        _expect(self.upper_price, Price, "upper_price")
        count = self.interval_count
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise GridError(
                GridErrorCode.INVALID_INTERVAL_COUNT,
                f"interval_count deve ser int >= 1 (recebido {count!r})",
            )
        if self.lower_price >= self.upper_price:
            raise GridError(
                GridErrorCode.LOWER_NOT_BELOW_UPPER,
                f"lower_price {self.lower_price} deve ser < upper_price {self.upper_price}",
            )

    @property
    def level_count(self) -> int:
        return self.interval_count + 1


@dataclass(frozen=True, slots=True)
class ArithmeticGridPlan:
    """Níveis exatos de um grid aritmético. Todos os invariantes são verificados aqui,
    então nem uma construção direta consegue produzir um plano inconsistente."""

    spec: ArithmeticGridSpec
    tick_size: Price
    levels: tuple[GridLevel, ...]

    def __post_init__(self) -> None:
        _expect(self.spec, ArithmeticGridSpec, "spec")
        _expect(self.tick_size, Price, "tick_size")
        if not isinstance(self.levels, tuple) or not all(
            isinstance(level, GridLevel) for level in self.levels
        ):
            raise TypeError("levels deve ser tuple[GridLevel, ...] (imutável)")
        spec, levels = self.spec, self.levels
        if len(levels) != spec.level_count:
            self._fail(f"{len(levels)} níveis; esperado {spec.level_count}")
        if [level.index for level in levels] != list(range(spec.level_count)):
            self._fail("índices devem ser 0..interval_count, em ordem")
        if levels[0].price != spec.lower_price or levels[-1].price != spec.upper_price:
            self._fail("primeiro/último nível devem ser lower_price/upper_price")
        if not all(is_multiple_of(level.price.value, self.tick_size.value) for level in levels):
            self._fail(f"nível fora da grade do tick {self.tick_size}")
        with financial():
            steps = {b.price.value - a.price.value for a, b in pairwise(levels)}
        if len(steps) != 1:
            self._fail("espaçamento entre níveis não é constante")

    @staticmethod
    def _fail(detail: str) -> None:
        raise GridError(GridErrorCode.PLAN_INVARIANT_VIOLATED, detail)

    @property
    def step(self) -> Decimal:
        """Distância constante entre níveis consecutivos."""
        with financial():
            return self.levels[1].price.value - self.levels[0].price.value

    @property
    def step_ticks(self) -> int:
        with financial():
            return int(self.step // self.tick_size.value)

    @property
    def prices(self) -> tuple[Price, ...]:
        return tuple(level.price for level in self.levels)


def build_arithmetic_grid(spec: ArithmeticGridSpec, rules: MarketRules) -> ArithmeticGridPlan:
    """Gera o grid exato em ticks inteiros, usando somente as regras de PREÇO do mercado.

    Ordem das verificações (o primeiro problema encontrado é reportado): mercado,
    alinhamento de lower e upper, faixa de preço de lower e upper, divisibilidade.
    """
    _expect(spec, ArithmeticGridSpec, "spec")
    _expect(rules, MarketRules, "rules")
    if spec.symbol != rules.symbol:
        raise GridError(
            GridErrorCode.SYMBOL_MISMATCH, f"grid de {spec.symbol} com regras de {rules.symbol}"
        )
    price_rules = rules.price
    tick = price_rules.tick_size.value
    for price, code in (
        (spec.lower_price, GridErrorCode.LOWER_PRICE_NOT_ALIGNED),
        (spec.upper_price, GridErrorCode.UPPER_PRICE_NOT_ALIGNED),
    ):
        if not is_multiple_of(price.value, tick):
            raise GridError(code, f"{price} não é múltiplo do tick {price_rules.tick_size}")
    for price, code in (
        (spec.lower_price, GridErrorCode.LOWER_PRICE_OUT_OF_RANGE),
        (spec.upper_price, GridErrorCode.UPPER_PRICE_OUT_OF_RANGE),
    ):
        below = price_rules.min_price is not None and price < price_rules.min_price
        above = price_rules.max_price is not None and price > price_rules.max_price
        if below or above:
            raise GridError(
                code,
                f"{price} fora de [{price_rules.min_price}, {price_rules.max_price}] (inclusivo)",
            )
    with financial():
        span_ticks = int((spec.upper_price.value - spec.lower_price.value) // tick)
    if span_ticks % spec.interval_count != 0:
        raise GridError(
            GridErrorCode.GRID_SPACING_NOT_REPRESENTABLE,
            f"{span_ticks} ticks não se dividem exatamente em {spec.interval_count} intervalos",
        )
    step_ticks = span_ticks // spec.interval_count
    with financial():
        levels = tuple(
            GridLevel(i, Price(spec.lower_price.value + Decimal(i * step_ticks) * tick))
            for i in range(spec.level_count)
        )
    return ArithmeticGridPlan(spec=spec, tick_size=price_rules.tick_size, levels=levels)
