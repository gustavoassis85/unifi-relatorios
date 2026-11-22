"""Períodos que o MSP pode escolher: últimos 7 dias, últimos 30 dias ou um mês fechado."""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

FUSO = ZoneInfo("America/Sao_Paulo")
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
         "outubro", "novembro", "dezembro"]
MESES_NA_LISTA = 13   # dados agregados ficam 13 meses


class PeriodoInvalido(ValueError):
    pass


def _mes_anterior(ano, mes):
    return (ano - 1, 12) if mes == 1 else (ano, mes - 1)


def opcoes(agora=None):
    """[(valor, rótulo)], com o mês anterior primeiro (é o padrão)."""
    local = timezone.localtime(agora or timezone.now(), FUSO)
    lista, ano, mes = [], local.year, local.month
    for _ in range(MESES_NA_LISTA):
        ano, mes = _mes_anterior(ano, mes)
        lista.append((f"mes:{ano}-{mes:02d}", f"{MESES[mes - 1].capitalize()} de {ano}"))
    return lista[:1] + [("30d", "Últimos 30 dias"), ("7d", "Últimos 7 dias")] + lista[1:]


def resolver(valor, agora=None):
    """Devolve (início, fim, rótulo). Só aceita os valores oferecidos em opcoes()."""
    agora = agora or timezone.now()
    if valor in ("7d", "30d"):
        dias = int(valor[:-1])
        return agora - timedelta(days=dias), agora, f"Últimos {dias} dias"
    if valor not in dict(opcoes(agora)):
        raise PeriodoInvalido("Período inválido.")
    ano, mes = (int(x) for x in re.fullmatch(r"mes:(\d{4})-(\d{2})", valor).groups())
    inicio = datetime(ano, mes, 1, tzinfo=FUSO)
    proximo = datetime(ano + (mes == 12), mes % 12 + 1, 1, tzinfo=FUSO)
    return inicio, proximo - timedelta(seconds=1), f"{MESES[mes - 1].capitalize()} de {ano}"
