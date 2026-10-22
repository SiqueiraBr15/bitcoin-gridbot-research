"""Nível de grid: só geometria (índice + preço). BUY/SELL não pertence ao nível (ADR-010)."""

from __future__ import annotations

from dataclasses import dataclass

from gridbot.domain.errors import DomainError
from gridbot.domain.values import Price


@dataclass(frozen=True, slots=True, order=True)
class GridLevel:
    """Nível do grid: índice (0 = mais baixo) e preço."""

    index: int
    price: Price

    def __post_init__(self) -> None:
        if isinstance(self.index, bool) or not isinstance(self.index, int) or self.index < 0:
            raise DomainError(f"GridLevel.index inválido: {self.index!r}")
        if not isinstance(self.price, Price):
            raise TypeError("GridLevel.price deve ser Price")
