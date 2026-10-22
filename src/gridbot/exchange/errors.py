"""Erros que qualquer implementação de ``ExchangePort`` pode levantar."""


class ExchangeError(Exception):
    """Base para erros de exchange."""


class ExchangeUnavailableError(ExchangeError):
    """Exchange inacessível; nenhuma ordem foi aceita com certeza."""


class OrderRejectedError(ExchangeError):
    """A exchange recusou a ordem explicitamente (filtro, saldo, LIMIT_MAKER cruzando...)."""


class DuplicateClientOrderIdError(ExchangeError):
    """Já existe ordem com o mesmo ``client_order_id``."""


class OrderStateUnknownError(ExchangeError):
    """Resultado do envio é desconhecido; consultar a ordem antes de qualquer reenvio."""
