"""Market data histórico: Candle OHLCV e CandleSeries (ADR-007, ADR-008).

Semântica temporal:
- todo instante é ``datetime`` timezone-aware em UTC;
- um candle cobre o intervalo semiaberto ``[open_time, close_time)``;
- ``close_time - open_time == timeframe.duration``.

OHLC_INTRABAR_PATH_UNKNOWN (ADR-008): um candle informa abertura, máxima, mínima e
fechamento, mas NÃO a ordem em que máxima e mínima ocorreram, nem o caminho entre elas.
Nada neste módulo infere trajetória intrabar, gera ticks sintéticos ou assume O-H-L-C /
O-L-H-C. Qualquer uso futuro (simulação de fills) exige uma política explícita.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from itertools import pairwise

from gridbot.domain.assets import Symbol
from gridbot.domain.errors import (
    CandleSequenceError,
    DomainError,
    DuplicateCandleError,
    FloatNotAllowedError,
    InvalidCandleError,
    OutOfOrderCandleError,
    OverlappingCandleError,
)
from gridbot.domain.time import require_utc
from gridbot.domain.timeframe import Timeframe
from gridbot.domain.values import Price, Qty

_ZERO = timedelta(0)


def _expect(value: object, expected: type, field: str) -> None:
    if isinstance(value, float):
        raise FloatNotAllowedError(field)
    if not isinstance(value, expected):
        raise TypeError(f"{field}: esperado {expected.__name__}, recebido {type(value).__name__}")


def _utc(value: object, field: str) -> datetime:
    try:
        return require_utc(value, field=field)
    except DomainError as exc:
        raise InvalidCandleError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class Candle:
    """Barra OHLCV imutável sobre ``[open_time, close_time)``, em UTC.

    ``symbol`` é o mercado (par base/quote); ``volume`` é em ativo base.
    Ver OHLC_INTRABAR_PATH_UNKNOWN no docstring do módulo.
    """

    symbol: Symbol
    timeframe: Timeframe
    open_time: datetime
    close_time: datetime
    open: Price
    high: Price
    low: Price
    close: Price
    volume: Qty

    def __post_init__(self) -> None:
        _expect(self.symbol, Symbol, "Candle.symbol")
        _expect(self.timeframe, Timeframe, "Candle.timeframe")
        for name in ("open", "high", "low", "close"):
            _expect(getattr(self, name), Price, f"Candle.{name}")
        _expect(self.volume, Qty, "Candle.volume")
        _utc(self.open_time, "Candle.open_time")
        _utc(self.close_time, "Candle.close_time")
        if self.open_time >= self.close_time:
            raise InvalidCandleError(
                f"open_time deve ser anterior a close_time ({self.open_time} >= {self.close_time})"
            )
        if self.close_time - self.open_time != self.timeframe.duration:
            raise InvalidCandleError(
                f"close_time - open_time ({self.close_time - self.open_time}) difere do "
                f"timeframe {self.timeframe}"
            )
        if self.high < max(self.open, self.close, self.low):
            raise InvalidCandleError(
                f"high {self.high} abaixo de open/close/low "
                f"(O={self.open} L={self.low} C={self.close})"
            )
        if self.low > min(self.open, self.close):
            raise InvalidCandleError(
                f"low {self.low} acima de open/close (O={self.open} C={self.close})"
            )


@dataclass(frozen=True, slots=True)
class CandleGap:
    """Intervalo sem candles dentro de uma série: ``[start, end)``.

    ``start`` = ``close_time`` do candle anterior; ``end`` = ``open_time`` do seguinte.
    """

    start: datetime
    end: datetime
    missing_bars: int

    def __post_init__(self) -> None:
        require_utc(self.start, field="gap.start")
        require_utc(self.end, field="gap.end")
        if self.start >= self.end:
            raise DomainError("gap exige start < end")
        if (
            isinstance(self.missing_bars, bool)
            or not isinstance(self.missing_bars, int)
            or self.missing_bars <= 0
        ):
            raise DomainError("gap.missing_bars deve ser int > 0")


@dataclass(frozen=True, slots=True)
class WindowCoverage:
    """Quanto de uma janela pedida ``[start, end)`` os candles de uma série cobrem.

    - ``missing_prefix``: tempo entre ``start`` e o primeiro candle (janela inteira se vazia);
    - ``missing_suffix``: tempo entre o último candle e ``end`` (zero se vazia);
    - ``gaps``: buracos internos (os mesmos de ``CandleSeries.gaps``).

    Só uma janela alinhada à grade de barras pode ficar completa. Nada é preenchido.
    """

    start: datetime
    end: datetime
    candle_count: int
    missing_prefix: timedelta
    missing_suffix: timedelta
    gaps: tuple[CandleGap, ...]

    def __post_init__(self) -> None:
        require_utc(self.start, field="coverage.start")
        require_utc(self.end, field="coverage.end")
        if self.start >= self.end:
            raise DomainError("coverage exige start < end")
        if (
            isinstance(self.candle_count, bool)
            or not isinstance(self.candle_count, int)
            or self.candle_count < 0
        ):
            raise DomainError("coverage.candle_count deve ser int >= 0")
        for name in ("missing_prefix", "missing_suffix"):
            value = getattr(self, name)
            if not isinstance(value, timedelta):
                raise TypeError(f"coverage.{name} deve ser timedelta")
            if value < _ZERO:
                raise DomainError(f"coverage.{name} não pode ser negativo")
        if not isinstance(self.gaps, tuple):
            raise TypeError("coverage.gaps deve ser tuple[CandleGap, ...] (imutável)")
        for gap in self.gaps:
            _expect(gap, CandleGap, "coverage.gap")
            replace(gap)
        if self.candle_count == 0:
            if (
                self.missing_prefix != self.end - self.start
                or self.missing_suffix != _ZERO
                or self.gaps
            ):
                raise DomainError("coverage vazia exige janela inteira ausente e nenhum gap")
            return
        duration = self.end - self.start
        if (
            self.missing_prefix >= duration
            or self.missing_suffix >= duration
            or self.missing_prefix + self.missing_suffix >= duration
        ):
            raise DomainError("coverage com candles exige duração coberta positiva")
        if len(self.gaps) >= self.candle_count:
            raise DomainError("coverage exige menos gaps internos que candles")
        first = self.start + self.missing_prefix
        last = self.end - self.missing_suffix
        previous_end = first
        for gap in self.gaps:
            if gap.start <= previous_end or gap.end >= last:
                raise DomainError("coverage exige gaps internos ordenados e separados por candles")
            previous_end = gap.end

    @property
    def has_missing_prefix(self) -> bool:
        return self.missing_prefix > _ZERO

    @property
    def has_missing_suffix(self) -> bool:
        return self.missing_suffix > _ZERO

    @property
    def has_gaps(self) -> bool:
        return bool(self.gaps)

    @property
    def is_complete(self) -> bool:
        return not (self.has_missing_prefix or self.has_missing_suffix or self.has_gaps)


@dataclass(frozen=True, slots=True)
class CandleSeries:
    """Sequência imutável e validada de candles de um único (mercado, timeframe).

    Inválido (levanta erro): mercado/timeframe misturados, ``open_time`` duplicado,
    fora de ordem, sobreposto, ou buraco que não é múltiplo do timeframe.
    Válido mas reportado: gaps (barras faltando). Gaps nunca são preenchidos.
    """

    symbol: Symbol
    timeframe: Timeframe
    candles: tuple[Candle, ...] = ()

    def __post_init__(self) -> None:
        _expect(self.symbol, Symbol, "CandleSeries.symbol")
        _expect(self.timeframe, Timeframe, "CandleSeries.timeframe")
        if not isinstance(self.candles, tuple):
            raise TypeError("CandleSeries.candles deve ser tuple (imutável)")
        for index, candle in enumerate(self.candles):
            _expect(candle, Candle, f"CandleSeries.candles[{index}]")
            if candle.symbol != self.symbol or candle.timeframe != self.timeframe:
                raise CandleSequenceError(
                    f"candle {index} é de {candle.symbol}/{candle.timeframe}; "
                    f"série é de {self.symbol}/{self.timeframe}"
                )
        for previous, current in pairwise(self.candles):
            self._check_successor(previous, current)

    def _check_successor(self, previous: Candle, current: Candle) -> None:
        at = current.open_time.isoformat()
        if current.open_time == previous.open_time:
            raise DuplicateCandleError(f"open_time duplicado: {at}")
        if current.open_time < previous.open_time:
            raise OutOfOrderCandleError(
                f"open_time {at} anterior ao precedente {previous.open_time.isoformat()}"
            )
        if current.open_time < previous.close_time:
            raise OverlappingCandleError(
                f"candle em {at} começa antes do fim do precedente "
                f"({previous.close_time.isoformat()})"
            )
        if (current.open_time - previous.close_time) % self.timeframe.duration != _ZERO:
            raise CandleSequenceError(
                f"candle em {at} desalinhado: buraco não é múltiplo de {self.timeframe}"
            )

    def __len__(self) -> int:
        return len(self.candles)

    def __iter__(self) -> Iterator[Candle]:
        return iter(self.candles)

    @property
    def start(self) -> datetime | None:
        """``open_time`` do primeiro candle (``None`` se vazia)."""
        return self.candles[0].open_time if self.candles else None

    @property
    def end(self) -> datetime | None:
        """``close_time`` do último candle (``None`` se vazia)."""
        return self.candles[-1].close_time if self.candles else None

    @property
    def gaps(self) -> tuple[CandleGap, ...]:
        """Buracos internos, em ordem. Não inclui falta de dados antes/depois da série."""
        return tuple(
            CandleGap(
                start=previous.close_time,
                end=current.open_time,
                missing_bars=(current.open_time - previous.close_time) // self.timeframe.duration,
            )
            for previous, current in pairwise(self.candles)
            if current.open_time > previous.close_time
        )

    @property
    def has_gaps(self) -> bool:
        return bool(self.gaps)

    def between(self, start: datetime, end: datetime) -> CandleSeries:
        """Candles inteiramente contidos em ``[start, end)``.

        Ou seja, ``start <= open_time`` e ``close_time <= end``. Um candle que cruza ``end``
        fica de fora (evita look-ahead). Exige ``start < end``, ambos em UTC.
        """
        require_utc(start, field="start")
        require_utc(end, field="end")
        if start >= end:
            raise DomainError(f"intervalo de consulta exige start < end ({start} >= {end})")
        lo = bisect_left(self.candles, start, key=lambda c: c.open_time)
        hi = bisect_right(self.candles, end, key=lambda c: c.close_time)
        return CandleSeries(self.symbol, self.timeframe, self.candles[lo:hi])

    def coverage(self, start: datetime, end: datetime) -> WindowCoverage:
        """Cobertura de ``[start, end)`` pelos candles desta série contidos na janela."""
        window = self.between(start, end)
        if window.start is None or window.end is None:
            return WindowCoverage(start, end, 0, end - start, _ZERO, ())
        return WindowCoverage(
            start=start,
            end=end,
            candle_count=len(window),
            missing_prefix=window.start - start,
            missing_suffix=end - window.end,
            gaps=window.gaps,
        )
