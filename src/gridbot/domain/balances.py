"""Saldo de um ativo (livre + travado em ordens)."""

from __future__ import annotations

from dataclasses import dataclass

from gridbot.domain.assets import Asset
from gridbot.domain.values import Qty


@dataclass(frozen=True, slots=True)
class Balance:
    asset: Asset
    free: Qty
    locked: Qty

    def __post_init__(self) -> None:
        if not isinstance(self.asset, Asset):
            raise TypeError("Balance.asset deve ser Asset")
        if not isinstance(self.free, Qty) or not isinstance(self.locked, Qty):
            raise TypeError("Balance.free/locked devem ser Qty")

    @property
    def total(self) -> Qty:
        return self.free + self.locked
