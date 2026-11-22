"""Funções usadas pelos testes de vários apps."""
from allauth.mfa.totp.internal.auth import (
    TOTP,
    format_hotp_value,
    generate_totp_secret,
    hotp_value,
    yield_hotp_counters_from_time,
)

SENHA = "senha-bem-longa-123"


def ativar_mfa(usuario):
    """Liga o app autenticador do usuário e devolve o segredo (para gerar códigos)."""
    segredo = generate_totp_secret()
    TOTP.activate(usuario, segredo)
    return segredo


def codigo_atual(segredo):
    return format_hotp_value(hotp_value(segredo, next(yield_hotp_counters_from_time())))
