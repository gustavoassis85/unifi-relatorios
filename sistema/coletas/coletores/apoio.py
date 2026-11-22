"""Conversões usadas pelas coletas: valores da API podem vir vazios ou em formato inesperado."""
from datetime import datetime, timezone as tz

from django.utils.dateparse import parse_datetime


def data(valor):
    """Texto ISO ("2026-11-21T10:00:00Z") ou número Unix (s ou ms) para data com fuso. None se inválido."""
    if valor in (None, ""):
        return None
    if isinstance(valor, (int, float)):
        segundos = valor / 1000 if valor > 1e11 else valor
        try:
            return datetime.fromtimestamp(segundos, tz=tz.utc)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        resultado = parse_datetime(str(valor))
    except ValueError:
        return None
    if resultado is not None and resultado.tzinfo is None:
        resultado = resultado.replace(tzinfo=tz.utc)
    return resultado


def numero(valor):
    try:
        return float(valor) if valor not in (None, "") else None
    except (TypeError, ValueError):
        return None


def inteiro(valor):
    n = numero(valor)
    return int(n) if n is not None else None


def texto(valor, tamanho):
    return str(valor)[:tamanho] if valor not in (None, "") else ""
