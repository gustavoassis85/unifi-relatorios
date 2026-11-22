"""Relatórios na página do cliente: gerar, histórico, ver e baixar o PDF."""
from datetime import timedelta

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from auditoria.models import Acao
from auditoria.registro import registrar
from clientes.models import Cliente
from organizacoes import papeis
from organizacoes.permissoes import exige

from .models import Relatorio, SituacaoRelatorio
from .periodos import PeriodoInvalido, opcoes, resolver
from .servicos import nome_do_pdf
from .tarefas import enfileirar_relatorio

# O HTML do relatório tem estilos embutidos e nenhum script: esta CSP só libera isso.
CSP_RELATORIO = ("default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; "
                 "form-action 'none'; frame-ancestors 'none'")
HISTORICO = 20
# A geração leva segundos; "gerando" há mais que isso é trabalhador que caiu no meio.
GERANDO_NO_MAXIMO = timedelta(minutes=15)
SEM_CACHE = "private, no-store"


def _encerrar_travados(cliente):
    limite = timezone.now() - GERANDO_NO_MAXIMO
    Relatorio.objects.filter(cliente=cliente, situacao=SituacaoRelatorio.GERANDO, pedido_em__lt=limite).update(
        situacao=SituacaoRelatorio.FALHOU, erro="A geração não terminou (o trabalhador parou no meio). Peça de novo.")


def historico(cliente):
    """Os relatórios mais recentes do cliente, sem carregar HTML e PDF (são grandes), cada um
    com o último envio por e-mail em .envio (ou None)."""
    from envios.models import Envio

    relatorios = list(Relatorio.objects.filter(cliente=cliente).defer("html", "pdf")
                      .select_related("pedido_por")[:HISTORICO])
    ultimos = {}
    for envio in Envio.objects.filter(relatorio__in=relatorios).order_by("criado_em"):
        ultimos[envio.relatorio_id] = envio
    for r in relatorios:
        r.envio = ultimos.get(r.pk)
    return relatorios


def contexto_relatorios(cliente):
    _encerrar_travados(cliente)
    relatorios = historico(cliente)
    ultimo_pronto = (Relatorio.objects.filter(cliente=cliente, situacao=SituacaoRelatorio.PRONTO)
                     .only("higiene", "pronto_em", "rotulo").first())
    return {
        "relatorios": relatorios,
        # A tela se atualiza sozinha enquanto gera ou enquanto a 1ª tentativa de envio não terminou.
        "gerando": any(r.situacao == SituacaoRelatorio.GERANDO
                       or (r.envio and r.envio.situacao == "pendente" and r.envio.tentativas == 0)
                       for r in relatorios),
        "opcoes_periodo": opcoes(),
        "higiene": ultimo_pronto.higiene if ultimo_pronto else [],
        "higiene_de": ultimo_pronto,
    }


def _relatorio_pronto(pk, relatorio_pk):
    cliente = get_object_or_404(Cliente.objects, pk=pk)
    relatorio = get_object_or_404(Relatorio.objects, pk=relatorio_pk, cliente=cliente)
    if relatorio.situacao != SituacaoRelatorio.PRONTO:
        raise Http404
    return cliente, relatorio


@exige(papeis.pode_gerar_relatorio)
@require_http_methods(["POST"])
def gerar(request, pk):
    # Trava a linha do cliente: dois cliques ao mesmo tempo não criam dois relatórios gerando.
    cliente = get_object_or_404(Cliente.objects.select_for_update(), pk=pk)
    voltar = redirect("clientes:detalhe", pk=cliente.pk)
    try:
        inicio, fim, rotulo = resolver(request.POST.get("periodo", ""))
    except PeriodoInvalido:
        messages.error(request, "Escolha um dos períodos da lista.")
        return voltar
    _encerrar_travados(cliente)
    if Relatorio.objects.filter(cliente=cliente, situacao=SituacaoRelatorio.GERANDO).exists():
        messages.error(request, "Já há um relatório deste cliente sendo gerado. Espere ele ficar pronto.")
        return voltar
    relatorio = Relatorio.objects.create(cliente=cliente, inicio=inicio, fim=fim, rotulo=rotulo,
                                         pedido_por=request.user)
    enfileirar_relatorio(relatorio)
    registrar(request, Acao.RELATORIO_PEDIDO, cliente_id=cliente.pk, cliente=cliente.nome,
              relatorio_id=relatorio.pk, periodo=rotulo)
    messages.success(request, "Relatório na fila. Ele fica pronto em instantes (o trabalhador precisa estar ligado).")
    return voltar


@exige(papeis.pode_ver_clientes)
def lista(request, pk):
    """Bloco do histórico (a página do cliente atualiza este pedaço enquanto há relatório gerando)."""
    cliente = get_object_or_404(Cliente.objects, pk=pk)
    return render(request, "relatorios/_historico.html", {"cliente": cliente, **contexto_relatorios(cliente)})


@exige(papeis.pode_ver_clientes)
def ver(request, pk, relatorio_pk):
    _cliente, relatorio = _relatorio_pronto(pk, relatorio_pk)
    resposta = HttpResponse(relatorio.html, content_type="text/html; charset=utf-8")
    resposta["Content-Security-Policy"] = CSP_RELATORIO
    resposta["Referrer-Policy"] = "no-referrer"
    resposta["Cache-Control"] = SEM_CACHE
    resposta._csp_exempt = True
    return resposta


@exige(papeis.pode_ver_clientes)
def baixar(request, pk, relatorio_pk):
    cliente, relatorio = _relatorio_pronto(pk, relatorio_pk)
    resposta = HttpResponse(bytes(relatorio.pdf), content_type="application/pdf")
    resposta["Cache-Control"] = SEM_CACHE
    resposta["Content-Disposition"] = f'attachment; filename="{nome_do_pdf(cliente, relatorio)}"'
    registrar(request, Acao.RELATORIO_BAIXADO, cliente_id=cliente.pk, cliente=cliente.nome,
              relatorio_id=relatorio.pk, periodo=relatorio.rotulo)
    return resposta
