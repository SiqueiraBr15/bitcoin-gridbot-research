"""Fonte histórica em memória: implementa ``MarketDataPort`` sem I/O, rede ou relógio."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from gridbot.domain.assets import Symbol
from gridbot.domain.errors import CandleSequenceError
from gridbot.domain.market import Candle, CandleSeries
from gridbot.domain.timeframe import Timeframe

type SeriesKey = tuple[Symbol, Timeframe]


class InMemoryMarketData:
    """Guarda uma ``CandleSeries`` por (mercado, timeframe) e responde consultas por janela.

    As séries são imutáveis e já validadas; consultas devolvem novas séries, nunca a
    estrutura interna. Uma segunda série para a mesma chave é erro (não há merge).
    """

    __slots__ = ("_series",)

    def __init__(self, series: Iterable[CandleSeries] = ()) -> None:
        store: dict[SeriesKey, CandleSeries] = {}
        for item in series:
            if not isinstance(item, CandleSeries):
                raise TypeError(f"esperado CandleSeries, recebido {type(item).__name__}")
            key = (item.symbol, item.timeframe)
            if key in store:
                raise CandleSequenceError(f"série duplicada para {item.symbol}/{item.timeframe}")
            store[key] = item
        self._series = store

    @classmethod
    def from_candles(cls, candles: Iterable[Candle]) -> InMemoryMarketData:
        """Agrupa por (mercado, timeframe) preservando a ordem recebida (sem reordenar)."""
        groups: dict[SeriesKey, list[Candle]] = {}
        for candle in candles:
            if not isinstance(candle, Candle):
                raise TypeError(f"esperado Candle, recebido {type(candle).__name__}")
            groups.setdefault((candle.symbol, candle.timeframe), []).append(candle)
        return cls(
            CandleSeries(symbol, timeframe, tuple(group))
            for (symbol, timeframe), group in groups.items()
        )

    def candles(
        self, symbol: Symbol, timeframe: Timeframe, start: datetime, end: datetime
    ) -> CandleSeries:
        series = self._series.get((symbol, timeframe))
        if series is None:
            series = CandleSeries(symbol, timeframe)
        return series.between(start, end)
