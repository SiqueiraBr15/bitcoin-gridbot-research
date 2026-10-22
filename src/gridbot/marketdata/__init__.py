"""Market data: port + adapters (memória; futuramente arquivos, banco, exchange)."""

from gridbot.marketdata.in_memory import InMemoryMarketData
from gridbot.marketdata.ports import MarketDataPort

__all__ = ["InMemoryMarketData", "MarketDataPort"]
