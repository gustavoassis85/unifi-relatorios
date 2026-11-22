"""Quando cada agendamento roda e qual período o relatório cobre.

Tudo no fuso de São Paulo. Se o trabalhador ficou parado e perdeu datas, a próxima
execução é calculada a partir de agora: o agendamento roda uma vez, não repete as perdidas.
"""
from datetime import datetime, timedelta

from django.utils import timezone

from relatorios.periodos import FUSO, MESES

from .models import Frequencia


def proxima(agendamento, depois_de=None):
    """O primeiro horário marcado depois de depois_de (padrão: agora)."""
    local = timezone.localtime(depois_de or timezone.now(), FUSO)
    if agendamento.frequencia == Frequencia.MENSAL:
        ano, mes = local.year, local.month
        while True:
            marcado = datetime(ano, mes, agendamento.dia_do_mes, agendamento.hora, tzinfo=FUSO)
            if marcado > local:
                return marcado
            ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    dias = (agendamento.dia_da_semana - local.weekday()) % 7
    dia = (local + timedelta(days=dias)).date()
    marcado = datetime(dia.year, dia.month, dia.day, agendamento.hora, tzinfo=FUSO)
    return marcado if marcado > local else marcado + timedelta(days=7)


def periodo(agendamento, quando):
    """(início, fim, rótulo) do relatório de uma execução em "quando"."""
    local = timezone.localtime(quando, FUSO)
    if agendamento.frequencia == Frequencia.MENSAL:
        ano, mes = (local.year - 1, 12) if local.month == 1 else (local.year, local.month - 1)
        inicio = datetime(ano, mes, 1, tzinfo=FUSO)
        fim = datetime(local.year, local.month, 1, tzinfo=FUSO) - timedelta(seconds=1)
        return inicio, fim, f"{MESES[mes - 1].capitalize()} de {ano}"
    return quando - timedelta(days=7), quando, "Últimos 7 dias"
