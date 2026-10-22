"""Regras de tempo do domínio: todo instante é ``datetime`` timezone-aware em UTC."""

from __future__ import annotations

from datetime import datetime, timedelta

from gridbot.domain.errors import DomainError

_ZERO = timedelta(0)


def require_utc(value: object, *, field: str = "timestamp") -> datetime:
    """Aceita apenas ``datetime`` com tzinfo e offset zero; rejeita naive e outros fusos."""
    if not isinstance(value, datetime):
        raise TypeError(f"{field}: esperado datetime, recebido {type(value).__name__}")
    offset = value.utcoffset()
    if offset is None:
        raise DomainError(f"{field}: datetime sem timezone (naive) não é permitido; use UTC")
    if offset != _ZERO:
        raise DomainError(f"{field}: datetime deve estar em UTC (offset recebido: {offset})")
    return value
