"""Erros de configuração."""


class ConfigError(Exception):
    """Configuração inválida ou ambígua. Mensagens nunca incluem valores de variáveis."""
