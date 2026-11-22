from django.contrib import messages
from django.core.cache import cache
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_http_methods

from auditoria.models import Acao
from auditoria.registro import registrar
from clientes.models import Cliente
from organizacoes import papeis
from organizacoes.isolamento import exigir_organizacao
from organizacoes.permissoes import exige

from .painel import coleta_pendente
from .tarefas import clientes_para_coletar, enfileirar_coleta

INTERVALO_COLETAR_AGORA = 10 * 60  # segundos entre dois pedidos para o mesmo cliente


@exige(papeis.pode_testar_conexao)
@require_http_methods(["POST"])
def coletar_agora(request, pk):
    cliente = get_object_or_404(Cliente.objects, pk=pk)
    org_id = exigir_organizacao()
    voltar = redirect("clientes:detalhe", pk=cliente.pk)

    if cliente.pk not in clientes_para_coletar(org_id):
        messages.error(request, "Para coletar, o cliente precisa de uma chave e de pelo menos um console acompanhado.")
        return voltar
    if coleta_pendente(cliente):
        messages.error(request, "Já há uma coleta deste cliente na fila.")
        return voltar
    if not cache.add(f"coletar-agora:{cliente.pk}", 1, timeout=INTERVALO_COLETAR_AGORA):
        messages.error(request, "Uma coleta deste cliente foi pedida há pouco. Espere 10 minutos para pedir de novo.")
        return voltar

    enfileirar_coleta(org_id, cliente.pk, pedida_por_id=request.user.pk)
    registrar(request, Acao.COLETA_PEDIDA, cliente_id=cliente.pk, cliente=cliente.nome)
    messages.success(request, "Coleta na fila. Ela roda assim que o trabalhador pegar (o trabalhador precisa estar ligado).")
    return voltar
