"""Identificadores determinísticos.

Backtest e replay precisam produzir exatamente os mesmos IDs a cada execução, então o
domínio não depende de UUID aleatório nem de relógio para gerar IDs. A lógica completa de
``clientOrderId`` (nível/lado/sequência) entra com o OrderManager.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from gridbot.domain.errors import DomainError

# Charset e tamanho aceitos pela Binance Spot para newClientOrderId.
_CLIENT_ORDER_ID = re.compile(r"[.A-Z:/a-z0-9_-]{1,36}")
_PREFIX = re.compile(r"[A-Za-z0-9_]{1,24}")
_MAX_LEN = 36


@dataclass(frozen=True, slots=True)
class ClientOrderId:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not _CLIENT_ORDER_ID.fullmatch(self.value):
            raise DomainError(f"ClientOrderId inválido: {self.value!r}")

    def __str__(self) -> str:
        return self.value


class IdGenerator(Protocol):
    def next_id(self) -> str: ...


class SequentialIdGenerator:
    """Gera ``<prefix>-<n>``: mesmo prefixo e mesmo início produzem a mesma sequência."""

    def __init__(self, prefix: str, start: int = 1) -> None:
        if not isinstance(prefix, str) or not _PREFIX.fullmatch(prefix):
            raise DomainError(f"prefixo de ID inválido: {prefix!r}")
        if isinstance(start, bool) or not isinstance(start, int) or start < 0:
            raise DomainError(f"início de sequência inválido: {start!r}")
        self._prefix = prefix
        self._next = start

    def next_id(self) -> str:
        candidate = f"{self._prefix}-{self._next}"
        if len(candidate) > _MAX_LEN:
            raise DomainError(f"sequência de IDs esgotada para o prefixo {self._prefix!r}")
        self._next += 1
        return candidate
