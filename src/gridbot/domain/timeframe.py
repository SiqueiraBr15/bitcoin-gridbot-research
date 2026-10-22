"""Timeframe: intervalo de barra de duração fixa, independente de exchange (ADR-007).

Decisão: nesta fase só existem durações fixas, em segundos inteiros (1m, 15m, 1h, 1d, 7d...).
Intervalos calendáricos (mês) não são representáveis. A conversão para/desde strings de API
(ex.: ``"1m"`` da Binance) pertence ao adapter da exchange, nunca ao domínio.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from gridbot.domain.errors import InvalidTimeframeError

_ZERO = timedelta(0)
_SECOND = timedelta(seconds=1)
_UNITS = (
    (timedelta(days=1), "d"),
    (timedelta(hours=1), "h"),
    (timedelta(minutes=1), "m"),
    (_SECOND, "s"),
)


def _positive_count(value: object, unit: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidTimeframeError(f"quantidade de {unit} deve ser int > 0 (recebido {value!r})")
    return value


@dataclass(frozen=True, slots=True, order=True)
class Timeframe:
    """Duração fixa de uma barra. Igualdade e ordenação pela duração."""

    duration: timedelta

    def __post_init__(self) -> None:
        if not isinstance(self.duration, timedelta):
            raise InvalidTimeframeError(
                f"duração deve ser timedelta (recebido {type(self.duration).__name__})"
            )
        if self.duration <= _ZERO:
            raise InvalidTimeframeError(f"duração deve ser positiva (recebido {self.duration})")
        if self.duration % _SECOND != _ZERO:
            raise InvalidTimeframeError(
                f"duração deve ser em segundos inteiros (recebido {self.duration})"
            )

    @classmethod
    def seconds(cls, count: int) -> Timeframe:
        return cls(timedelta(seconds=_positive_count(count, "segundos")))

    @classmethod
    def minutes(cls, count: int) -> Timeframe:
        return cls(timedelta(minutes=_positive_count(count, "minutos")))

    @classmethod
    def hours(cls, count: int) -> Timeframe:
        return cls(timedelta(hours=_positive_count(count, "horas")))

    @classmethod
    def days(cls, count: int) -> Timeframe:
        return cls(timedelta(days=_positive_count(count, "dias")))

    def __str__(self) -> str:
        """Rótulo legível (``15m``, ``4h``, ``1d``); não é formato de API de exchange."""
        for unit, suffix in _UNITS:
            if self.duration % unit == _ZERO:
                return f"{self.duration // unit}{suffix}"
        return f"{self.duration // _SECOND}s"  # pragma: no cover - _UNITS termina em 1s
