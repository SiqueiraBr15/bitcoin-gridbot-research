"""Tabela de taxas (fee rates) por papel de liquidez (ADR-009).

Escopo deliberadamente limitado:
- aqui existem só TAXAS (frações, ex.: ``0.001`` = 0,1%);
- o VALOR da fee e o ATIVO em que ela é cobrada (base, quote, token de desconto...)
  pertencem à execução/fill e serão definidos em fase futura; nada aqui assume USDT;
- o papel (MAKER/TAKER) é determinado pela execução, não pelo tipo da ordem: uma LIMIT pode
  executar como TAKER.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from gridbot.domain.decimals import DecimalInput, require_finite, to_decimal
from gridbot.domain.enums import LiquidityRole
from gridbot.domain.errors import InvalidMarketRulesError

_ZERO = Decimal(0)
_ONE = Decimal(1)


def _check_rate(value: Decimal, field: str) -> None:
    require_finite(value, field=field)
    if not (_ZERO <= value < _ONE):
        raise InvalidMarketRulesError(f"{field} deve estar em [0, 1) (recebido {value})")


@dataclass(frozen=True, slots=True)
class FeeSchedule:
    maker_rate: Decimal
    taker_rate: Decimal

    def __post_init__(self) -> None:
        _check_rate(self.maker_rate, "maker_rate")
        _check_rate(self.taker_rate, "taker_rate")

    @classmethod
    def parse(cls, maker_rate: DecimalInput, taker_rate: DecimalInput) -> FeeSchedule:
        return cls(
            to_decimal(maker_rate, field="maker_rate"),
            to_decimal(taker_rate, field="taker_rate"),
        )

    def rate_for(self, role: LiquidityRole) -> Decimal:
        if not isinstance(role, LiquidityRole):
            raise TypeError(f"esperado LiquidityRole, recebido {type(role).__name__}")
        return self.maker_rate if role is LiquidityRole.MAKER else self.taker_rate
