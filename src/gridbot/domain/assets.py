"""Ativos e símbolos negociáveis."""

from __future__ import annotations

import re
from dataclasses import dataclass

from gridbot.domain.errors import DomainError

_ASSET_CODE = re.compile(r"[A-Z0-9]{2,20}")


@dataclass(frozen=True, slots=True)
class Asset:
    """Código de ativo em maiúsculas, ex.: ``BTC``, ``USDT``."""

    code: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not _ASSET_CODE.fullmatch(self.code):
            raise DomainError(f"Asset inválido: {self.code!r} (esperado [A-Z0-9]{{2,20}})")

    def __str__(self) -> str:
        return self.code


@dataclass(frozen=True, slots=True)
class Symbol:
    """Par negociável ``base/quote``, ex.: BTC/USDT (nome de exchange: ``BTCUSDT``)."""

    base: Asset
    quote: Asset

    def __post_init__(self) -> None:
        if not isinstance(self.base, Asset) or not isinstance(self.quote, Asset):
            raise TypeError("Symbol exige base e quote do tipo Asset")
        if self.base == self.quote:
            raise DomainError(f"Symbol inválido: base e quote iguais ({self.base})")

    @property
    def name(self) -> str:
        return f"{self.base.code}{self.quote.code}"

    def __str__(self) -> str:
        return self.name


BTC = Asset("BTC")
USDT = Asset("USDT")
BTCUSDT = Symbol(base=BTC, quote=USDT)
