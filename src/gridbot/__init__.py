"""GridBot: bot de Grid Spot BTC/USDT.

Fase 0 (fundação): nenhum código deste pacote envia ordens reais.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("gridbot")
except PackageNotFoundError:  # pragma: no cover - só ocorre sem instalação
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
