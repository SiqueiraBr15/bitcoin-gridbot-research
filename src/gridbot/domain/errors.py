"""Exceções do domínio."""


class DomainError(ValueError):
    """Violação de invariante de domínio (valor inválido, estado impossível)."""


class FloatNotAllowedError(TypeError):
    """Tentativa de usar ``float`` onde o domínio exige ``Decimal`` (ADR-002)."""

    def __init__(self, field: str) -> None:
        super().__init__(
            f"{field}: float não é permitido em valores financeiros; use str, int ou Decimal"
        )
        self.field = field


# ------------------------------------------------------------------ market data (ADR-007)


class InvalidTimeframeError(DomainError):
    """Timeframe com duração inválida (não positiva ou fração de segundo)."""


class InvalidCandleError(DomainError):
    """Candle que viola um invariante (OHLC, tempo, duração do timeframe)."""


class CandleSequenceError(DomainError):
    """Sequência de candles inválida (mistura de mercado/timeframe, desalinhamento)."""


class DuplicateCandleError(CandleSequenceError):
    """Dois candles com o mesmo ``open_time``."""


class OutOfOrderCandleError(CandleSequenceError):
    """Candle com ``open_time`` anterior ao do candle precedente."""


class OverlappingCandleError(CandleSequenceError):
    """Candle que começa antes do ``close_time`` do candle precedente."""


# ------------------------------------------------------------------ regras de mercado (ADR-009)


class InvalidMarketRulesError(DomainError):
    """Regras de mercado ou de fee inconsistentes (falham na construção)."""


class MarketRuleViolationError(DomainError):
    """Proposta (preço, quantidade) rejeitada; ``check`` traz todas as violações."""

    def __init__(self, message: str, check: object) -> None:
        super().__init__(message)
        self.check = check
