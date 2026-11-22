"""Tarefas periódicas, disparadas pelo próprio trabalhador (sem Agendador do Windows).

@periodica("nome", minuto=30)          de hora em hora, no minuto 30
@periodica("nome", hora=3, minuto=15)  todo dia às 3h15

Horários no fuso do sistema (America/Sao_Paulo). Se o trabalhador ficou parado, a
periódica roda uma vez assim que ele volta (não repete as horas perdidas). A última
vez fica no banco, com trava: com vários trabalhadores, só um dispara.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import Periodica

log = logging.getLogger("tarefas")

_periodicas = []


def periodica(nome, *, minuto, hora=None):
    def registrar(funcao):
        _periodicas.append((nome, hora, minuto, funcao))
        return funcao

    return registrar


def ultimo_horario(agora, hora, minuto):
    """O horário marcado mais recente que já passou."""
    local = timezone.localtime(agora)
    if hora is None:
        marcado = local.replace(minute=minuto, second=0, microsecond=0)
        return marcado if marcado <= local else marcado - timedelta(hours=1)
    marcado = local.replace(hour=hora, minute=minuto, second=0, microsecond=0)
    return marcado if marcado <= local else marcado - timedelta(days=1)


def rodar_periodicas(agora=None):
    """Dispara as periódicas vencidas. Devolve os nomes das que rodaram."""
    agora = agora or timezone.now()
    rodaram = []
    for nome, hora, minuto, funcao in _periodicas:
        marcado = ultimo_horario(agora, hora, minuto)
        try:
            with transaction.atomic():
                registro, _ = Periodica.objects.select_for_update().get_or_create(nome=nome)
                if registro.ultima_vez and registro.ultima_vez >= marcado:
                    continue
                funcao(agora)
                registro.ultima_vez = marcado
                registro.save(update_fields=["ultima_vez"])
                rodaram.append(nome)
        except Exception:  # noqa: BLE001 - uma periódica com erro não derruba as outras
            log.exception("Erro na tarefa periódica %s", nome)
    return rodaram


def nomes():
    return [nome for nome, *_ in _periodicas]
