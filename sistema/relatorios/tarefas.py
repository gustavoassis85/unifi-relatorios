"""Tarefa do trabalhador que gera o relatório (HTML + PDF) e a limpeza dos relatórios antigos."""
import logging
from datetime import timedelta

from django.utils import timezone

from organizacoes.isolamento import contexto
from organizacoes.models import Organizacao
from tarefas.fila import ErroDefinitivo, enfileirar, tarefa
from tarefas.periodicas import periodica

from .models import Relatorio, SituacaoRelatorio
from .montagem import montar
from .pdf import ErroPdf, gerar_pdf
from .sinais import relatorio_pronto

log = logging.getLogger("relatorios")

TIPO = "gerar_relatorio"
GUARDAR_POR = timedelta(days=396)   # 13 meses, como os dados agregados


def enfileirar_relatorio(relatorio):
    return enfileirar(TIPO, organizacao_id=relatorio.organizacao_id, cliente_id=relatorio.cliente_id,
                      exclusiva=f"{TIPO}:{relatorio.pk}", pedida_por_id=relatorio.pedido_por_id,
                      max_tentativas=1, relatorio_id=relatorio.pk)


@tarefa(TIPO)
def gerar_relatorio(tarefa_):
    org_id = tarefa_.organizacao_id
    with contexto(organizacao_id=org_id):
        relatorio = Relatorio.objects.select_related("cliente").filter(pk=tarefa_.parametros.get("relatorio_id")).first()
        if relatorio is None:
            raise ErroDefinitivo("O relatório não existe mais.")

    def falhou(mensagem):
        with contexto(organizacao_id=org_id):
            relatorio.situacao = SituacaoRelatorio.FALHOU
            relatorio.erro = mensagem[:300]
            relatorio.save(update_fields=["situacao", "erro"])
        raise ErroDefinitivo(mensagem)

    try:
        with contexto(organizacao_id=org_id):
            montado = montar(relatorio.cliente, relatorio.inicio, relatorio.fim)
        pdf = gerar_pdf(montado.html)
    except ErroPdf as erro:
        falhou(str(erro))
    except Exception as erro:  # noqa: BLE001 - qualquer outro problema vira mensagem no histórico
        log.exception("Erro ao gerar o relatório %s", relatorio.pk)
        falhou(f"Erro inesperado ao montar o relatório ({erro.__class__.__name__}).")

    with contexto(organizacao_id=org_id):
        relatorio.html = montado.html
        relatorio.pdf = pdf
        relatorio.higiene = [{"titulo": a.titulo, "evidencia": a.evidencia} for a in montado.higiene]
        relatorio.situacao = SituacaoRelatorio.PRONTO
        relatorio.pronto_em = timezone.now()
        relatorio.save(update_fields=["html", "pdf", "higiene", "situacao", "pronto_em"])
    if montado.erros:
        log.warning("Relatório %s saiu com regras em erro: %s", relatorio.pk, montado.erros)
    for receptor, resultado in relatorio_pronto.send_robust(sender=Relatorio, relatorio=relatorio):
        if isinstance(resultado, Exception):
            log.error("Erro em %s depois do relatório %s ficar pronto", receptor.__qualname__, relatorio.pk,
                      exc_info=resultado)


@periodica("apagar_relatorios_antigos", hora=4, minuto=10)
def apagar_relatorios_antigos(agora):
    total = 0
    for org_id in Organizacao.objects.values_list("pk", flat=True):
        with contexto(organizacao_id=org_id):
            total += Relatorio.objects.filter(pedido_em__lt=agora - GUARDAR_POR).delete()[0]
    log.info("Relatórios antigos apagados: %s", total)
    return total
