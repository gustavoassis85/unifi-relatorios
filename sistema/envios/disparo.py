"""Periódica que dispara os agendamentos vencidos.

Roda de hora em hora, no minuto 1 (os agendamentos são em hora cheia). Para cada agendamento
vencido: cria o relatório (origem: agendado), enfileira a geração e marca a próxima execução.
Se o trabalhador ficou parado, cada agendamento atrasado roda uma vez só (agenda.proxima
parte de agora). O envio por e-mail acontece quando o relatório fica pronto (envios/tarefas.py).
"""
import logging

from django.db import transaction

from organizacoes.isolamento import contexto
from organizacoes.models import Organizacao
from relatorios.models import Origem, Relatorio, SituacaoRelatorio
from relatorios.tarefas import enfileirar_relatorio
from tarefas.periodicas import periodica

from .agenda import periodo, proxima
from .models import Agendamento

log = logging.getLogger("envios")


def disparar_da_organizacao(org_id, agora):
    criados = 0
    with contexto(organizacao_id=org_id):
        vencidos = (Agendamento.objects.select_for_update(skip_locked=True).select_related("cliente")
                    .filter(ativo=True, proxima_execucao__lte=agora))
        for agendamento in vencidos:
            marcado = agendamento.proxima_execucao
            ainda_gerando = Relatorio.objects.filter(agendamento=agendamento,
                                                     situacao=SituacaoRelatorio.GERANDO).exists()
            if ainda_gerando:
                log.warning("Agendamento %s: o relatório anterior ainda está gerando; esta execução foi pulada.",
                            agendamento.pk)
            else:
                inicio, fim, rotulo = periodo(agendamento, marcado)
                relatorio = Relatorio.objects.create(
                    cliente=agendamento.cliente, inicio=inicio, fim=fim, rotulo=rotulo,
                    origem=Origem.AGENDADO, agendamento=agendamento, pedido_em=agora,
                )
                enfileirar_relatorio(relatorio)
                criados += 1
            agendamento.ultima_execucao = agora
            agendamento.proxima_execucao = proxima(agendamento, agora)
            agendamento.save(update_fields=["ultima_execucao", "proxima_execucao"])
    return criados


@periodica("disparar_agendamentos", minuto=1)
def disparar_agendamentos(agora):
    total = 0
    for org_id in Organizacao.objects.values_list("pk", flat=True):
        try:
            with transaction.atomic():   # um MSP com problema não segura os outros
                total += disparar_da_organizacao(org_id, agora)
        except Exception:  # noqa: BLE001
            log.exception("Erro ao disparar os agendamentos da organização %s", org_id)
    if total:
        log.info("Relatórios agendados disparados: %s", total)
    return total
