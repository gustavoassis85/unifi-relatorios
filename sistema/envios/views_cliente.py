"""Agendamentos na página do cliente: criar, editar, pausar, retomar e excluir."""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from auditoria.models import Acao
from auditoria.registro import registrar
from clientes.models import Cliente
from organizacoes import papeis
from organizacoes.permissoes import exige

from .agenda import proxima
from .forms import AgendamentoForm
from .models import Agendamento, ConfigSmtp


def contexto_agendamentos(cliente):
    smtp = ConfigSmtp.objects.only("ativo").first()
    return {
        "agendamentos": list(Agendamento.objects.filter(cliente=cliente)),
        "smtp_ativo": bool(smtp and smtp.ativo),
    }


def _detalhes(agendamento):
    # Sem os e-mails: na auditoria só a quantidade de destinatários.
    return {"cliente_id": agendamento.cliente_id, "agendamento_id": agendamento.pk,
            "frequencia": agendamento.descricao, "destinatarios": len(agendamento.destinatarios)}


def _do_cliente(pk, agendamento_pk):
    cliente = get_object_or_404(Cliente.objects, pk=pk)
    return cliente, get_object_or_404(Agendamento.objects, pk=agendamento_pk, cliente=cliente)


def _voltar(cliente):
    return redirect("clientes:detalhe", pk=cliente.pk)


@exige(papeis.pode_agendar)
@require_http_methods(["GET", "POST"])
def novo(request, pk):
    cliente = get_object_or_404(Cliente.objects, pk=pk)
    form = AgendamentoForm(request.POST or None, cliente=cliente)
    if request.method == "POST" and form.is_valid():
        agendamento = form.save(commit=False)
        agendamento.criado_por = request.user
        agendamento.save()
        registrar(request, Acao.AGENDAMENTO_CRIADO, **_detalhes(agendamento))
        messages.success(request, f"Agendamento criado: {agendamento.descricao}.")
        return _voltar(cliente)
    return render(request, "envios/agendamento_form.html", {"cliente": cliente, "form": form})


@exige(papeis.pode_agendar)
@require_http_methods(["GET", "POST"])
def editar(request, pk, agendamento_pk):
    cliente, agendamento = _do_cliente(pk, agendamento_pk)
    form = AgendamentoForm(request.POST or None, instance=agendamento, cliente=cliente)
    if request.method == "POST" and form.is_valid():
        agendamento = form.save()
        registrar(request, Acao.AGENDAMENTO_ALTERADO, **_detalhes(agendamento))
        messages.success(request, f"Agendamento salvo: {agendamento.descricao}.")
        return _voltar(cliente)
    return render(request, "envios/agendamento_form.html",
                  {"cliente": cliente, "form": form, "agendamento": agendamento})


@exige(papeis.pode_agendar)
@require_http_methods(["POST"])
def pausar(request, pk, agendamento_pk):
    cliente, agendamento = _do_cliente(pk, agendamento_pk)
    ligar = request.POST.get("ativo") == "1"
    if ligar != agendamento.ativo:
        agendamento.ativo = ligar
        agendamento.proxima_execucao = proxima(agendamento) if ligar else None
        agendamento.save(update_fields=["ativo", "proxima_execucao"])
        registrar(request, Acao.AGENDAMENTO_RETOMADO if ligar else Acao.AGENDAMENTO_PAUSADO, **_detalhes(agendamento))
        messages.success(request, f"Agendamento {'retomado' if ligar else 'pausado'}: {agendamento.descricao}.")
    return _voltar(cliente)


@exige(papeis.pode_agendar)
@require_http_methods(["GET", "POST"])
def excluir(request, pk, agendamento_pk):
    cliente, agendamento = _do_cliente(pk, agendamento_pk)
    if request.method == "POST":
        detalhes = _detalhes(agendamento)
        agendamento.delete()
        registrar(request, Acao.AGENDAMENTO_EXCLUIDO, **detalhes)
        messages.success(request, f"Agendamento excluído: {detalhes['frequencia']}.")
        return _voltar(cliente)
    return render(request, "envios/agendamento_excluir.html", {"cliente": cliente, "agendamento": agendamento})
