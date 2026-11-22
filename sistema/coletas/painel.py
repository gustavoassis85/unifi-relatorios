"""O que a página do cliente mostra sobre as coletas."""
from django.db.models import Max

from organizacoes.isolamento import exigir_organizacao
from tarefas.models import Situacao, Tarefa

from .models import ConsoleEstado, ExecucaoColeta
from .tarefas import TIPO


def coleta_pendente(cliente):
    """Tarefa de coleta do cliente na fila ou rodando (a fila não tem RLS: filtra pela organização)."""
    return (
        Tarefa.objects.filter(
            tipo=TIPO, organizacao_id=exigir_organizacao(), cliente_id=cliente.pk,
            situacao__in=[Situacao.FILA, Situacao.RODANDO],
        )
        .order_by("criada_em")
        .first()
    )


def situacao_das_coletas(cliente, consoles):
    ultimas = dict(
        ConsoleEstado.objects.filter(cliente=cliente)
        .values_list("console_id")
        .annotate(Max("coletado_em"))
    )
    for console in consoles:
        console.ultima_coleta = ultimas.get(console.pk)
    return {
        "ultima_execucao": ExecucaoColeta.objects.filter(cliente=cliente).first(),
        "coleta_pendente": coleta_pendente(cliente),
    }
