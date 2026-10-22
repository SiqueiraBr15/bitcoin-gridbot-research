"""Grade de incrementos: múltiplo exato, floor e ceil (ADR-009).

Regras:
- "alinhado" significa múltiplo matemático exato do incremento: ``value % increment == 0``.
  Nunca se compara número de casas decimais (com step 0.05, ``0.07`` NÃO é alinhado);
- sem epsilon e sem float;
- quantizar é sempre uma chamada explícita (floor ou ceil). Validar nunca altera valores;
- não existe "nearest": a direção é sempre escolhida pelo chamador;
- valores e incrementos não negativos; incremento > 0;
- operação que excede a precisão financeira levanta ``DomainError`` (nunca arredonda).
"""

from __future__ import annotations

from decimal import Decimal, DecimalException

from gridbot.domain.decimals import financial, require_finite
from gridbot.domain.errors import DomainError

_ZERO = Decimal(0)


def _remainder(value: Decimal, increment: Decimal) -> Decimal:
    require_finite(value, field="value")
    require_finite(increment, field="increment")
    if increment <= _ZERO:
        raise DomainError(f"incremento deve ser > 0 (recebido {increment})")
    if value < _ZERO:
        raise DomainError(f"valor deve ser >= 0 (recebido {value})")
    try:
        with financial():
            return value % increment
    except DecimalException as exc:
        raise DomainError(
            f"{value} / {increment} excede a precisão financeira; nenhum arredondamento feito"
        ) from exc


def is_multiple_of(value: Decimal, increment: Decimal) -> bool:
    """``True`` se ``value`` é múltiplo exato de ``increment``."""
    return _remainder(value, increment) == _ZERO


def floor_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    """Maior múltiplo de ``increment`` que é ``<= value``."""
    remainder = _remainder(value, increment)
    try:
        with financial():
            return value - remainder
    except DecimalException as exc:  # pragma: no cover - resto cabe na precisão do valor
        raise DomainError(f"floor de {value} excede a precisão financeira") from exc


def ceil_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    """Menor múltiplo de ``increment`` que é ``>= value``."""
    remainder = _remainder(value, increment)
    if remainder == _ZERO:
        return value
    try:
        with financial():
            return value - remainder + increment
    except DecimalException as exc:
        raise DomainError(f"ceil de {value} excede a precisão financeira") from exc
