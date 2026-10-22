"""Port de dados de mercado históricos (ADR-007).

Implementações: ``InMemoryMarketData`` (Fase A1). Futuras: arquivos/banco (Fase A),
Binance (Fase C, com conversão de timeframe no adapter). Streaming ao vivo será definido
na Fase C, separadamente.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from gridbot.domain.assets import Symbol
from gridbot.domain.market import CandleSeries
from gridbot.domain.timeframe import Timeframe


class MarketDataPort(Protocol):
    def candles(
        self, symbol: Symbol, timeframe: Timeframe, start: datetime, end: datetime
    ) -> CandleSeries:
        """Candles de ``(symbol, timeframe)`` inteiramente contidos em ``[start, end)``.

        Contrato:
        - ``start``/``end`` em UTC e ``start < end``; senão ``DomainError``;
        - inclui o candle se ``start <= open_time`` e ``close_time <= end``;
        - resultado imutável, em ordem cronológica, determinístico (mesma consulta,
          mesmo resultado);
        - sem dados: série vazia (não é erro);
        - gaps não são preenchidos; ficam visíveis em ``CandleSeries.gaps``.
        """
        ...
