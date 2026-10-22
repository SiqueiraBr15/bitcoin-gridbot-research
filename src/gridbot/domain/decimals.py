"""Conversão e aritmética decimal para valores financeiros (ADR-002).

Regras:
- dinheiro, preço, quantidade, taxa, saldo e PnL usam ``Decimal``;
- entradas aceitas: ``str``, ``int`` ou ``Decimal`` -- ``float`` é sempre rejeitado;
- NaN, Infinity e sNaN são sempre rejeitados;
- aritmética do domínio roda em ``FINANCIAL_CONTEXT``, que trata arredondamento implícito
  (``Inexact``) como erro: qualquer arredondamento deve ser explícito (ex.: ajuste a
  tickSize/stepSize, que entra na Fase A).
"""

from __future__ import annotations

import re
from contextlib import AbstractContextManager
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    localcontext,
)

from gridbot.domain.errors import DomainError, FloatNotAllowedError

FINANCIAL_PRECISION = 34

FINANCIAL_CONTEXT = Context(
    prec=FINANCIAL_PRECISION,
    rounding=ROUND_HALF_EVEN,
    traps=[InvalidOperation, DivisionByZero, Overflow, Inexact],
)

# Formato decimal estrito: sem espaços, underscores, NaN ou Infinity.
_DECIMAL_LITERAL = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")

type DecimalInput = str | int | Decimal


def financial() -> AbstractContextManager[Context]:
    """Contexto decimal para aritmética financeira do domínio."""
    return localcontext(FINANCIAL_CONTEXT)


def to_decimal(raw: DecimalInput, *, field: str = "value") -> Decimal:
    """Converte ``str``/``int``/``Decimal`` em ``Decimal`` finito.

    A anotação impede ``float`` estaticamente (mypy); a checagem em runtime cobre o resto.
    """
    return _coerce(raw, field)


def require_finite(value: object, *, field: str = "value") -> Decimal:
    """Garante que ``value`` já é um ``Decimal`` finito (sem conversão)."""
    if isinstance(value, float):
        raise FloatNotAllowedError(field)
    if not isinstance(value, Decimal):
        raise TypeError(f"{field}: esperado Decimal, recebido {type(value).__name__}")
    if not value.is_finite():
        raise DomainError(f"{field}: valor não finito não é permitido ({value})")
    return value


def _coerce(raw: object, field: str) -> Decimal:
    if isinstance(raw, bool):
        raise DomainError(f"{field}: bool não é aceito como número")
    if isinstance(raw, float):
        raise FloatNotAllowedError(field)
    if isinstance(raw, Decimal):
        value = raw
    elif isinstance(raw, int):
        value = Decimal(raw)
    elif isinstance(raw, str):
        if not _DECIMAL_LITERAL.fullmatch(raw):
            raise DomainError(f"{field}: literal decimal inválido: {raw!r}")
        value = Decimal(raw)
    else:
        raise TypeError(f"{field}: tipo não suportado: {type(raw).__name__}")
    return require_finite(value, field=field)
