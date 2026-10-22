"""Port de exchange (ADR-001, ADR-005).

Strategy, Risk, OrderManager e Portfolio falam apenas com esta interface. Implementações:
- ``exchange.simulated`` (backtest e paper; Fase A/B);
- ``exchange.binance`` (testnet e live; Fase C.5/D), adapter fino próprio com httpx +
  websockets, que faz a ponte da I/O assíncrona para esta interface.

Contrato que toda implementação deve respeitar:
- ``place_order`` é idempotente por ``client_order_id``: repetir o mesmo ID nunca cria uma
  segunda ordem (levanta ``DuplicateClientOrderIdError``);
- se o resultado de um envio for desconhecido (timeout, erro 5xx), levantar
  ``OrderStateUnknownError`` -- o chamador deve consultar ``get_order`` antes de reenviar;
- todos os valores financeiros chegam e saem como ``Decimal`` (via Price/Qty/Money).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from gridbot.domain.assets import Asset, Symbol
from gridbot.domain.balances import Balance
from gridbot.domain.ids import ClientOrderId
from gridbot.domain.orders import Fill, OrderIntent, OrderSnapshot


class ExchangePort(Protocol):
    def place_order(self, intent: OrderIntent) -> OrderSnapshot:
        """Envia a ordem descrita por ``intent`` e devolve o estado aceito."""
        ...

    def cancel_order(self, symbol: Symbol, client_order_id: ClientOrderId) -> OrderSnapshot:
        """Cancela a ordem e devolve o estado final (pode ter fill parcial)."""
        ...

    def get_order(self, symbol: Symbol, client_order_id: ClientOrderId) -> OrderSnapshot | None:
        """Estado atual da ordem, ou ``None`` se a exchange não a conhece."""
        ...

    def open_orders(self, symbol: Symbol) -> Sequence[OrderSnapshot]:
        """Ordens abertas (NEW / PARTIALLY_FILLED) do símbolo."""
        ...

    def fills_since(self, symbol: Symbol, after_trade_id: str | None) -> Sequence[Fill]:
        """Fills posteriores a ``after_trade_id`` (todos, se ``None``), em ordem."""
        ...

    def balances(self) -> Mapping[Asset, Balance]:
        """Saldos livres e travados por ativo."""
        ...
