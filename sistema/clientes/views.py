from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from auditoria.models import Acao
from auditoria.registro import registrar
from organizacoes import papeis
from organizacoes.permissoes import exige

from .forms import ClienteForm
from .models import Cliente


def _cliente_da_organizacao(pk):
    # Cliente.objects só enxerga a organização atual: de outra organização dá 404.
    return get_object_or_404(Cliente.objects, pk=pk)


@exige(papeis.pode_ver_clientes)
def lista(request):
    from .situacao import FILTROS, filtrar, situacao_dos_clientes

    visao = "lista" if request.GET.get("visao") == "lista" else "quadros"
    filtro = request.GET.get("situacao") if request.GET.get("situacao") in dict(FILTROS) else "todos"
    busca = request.GET.get("busca", "")
    todas = situacao_dos_clientes(Cliente.objects.all())
    return render(request, "clientes/lista.html", {
        "situacoes": filtrar(todas, filtro, busca), "total": len(todas), "visao": visao,
        "filtro": filtro, "busca": busca,
    })


@exige(papeis.pode_ver_clientes)
@require_http_methods(["GET"])
def painel(request):
    """Lista do painel lateral, filtrada (a busca e o filtro do painel pedem este pedaço)."""
    from .situacao import FILTROS, filtrar, situacao_dos_clientes

    filtro = request.GET.get("situacao") if request.GET.get("situacao") in dict(FILTROS) else "todos"
    busca = request.GET.get("busca", "")
    atual = request.GET.get("atual", "")
    situacoes = filtrar(situacao_dos_clientes(Cliente.objects.all(), completo=False), filtro, busca)
    return render(request, "clientes/_lista_painel.html", {
        "situacoes": situacoes, "filtrado": filtro != "todos" or bool(busca.strip()),
        "cliente": {"pk": int(atual)} if atual.isdigit() else None,
    })


@exige(papeis.pode_ver_clientes)
def detalhe(request, pk):
    from conexoes.views import chave_do_cliente

    from conexoes.models import Console

    from coletas.painel import situacao_das_coletas
    from envios.views_cliente import contexto_agendamentos
    from relatorios.views_cliente import contexto_relatorios

    from .situacao import situacao_dos_clientes

    cliente = _cliente_da_organizacao(pk)
    consoles = list(Console.objects.filter(cliente=cliente))
    contexto = {
        "cliente": cliente,
        "situacao": situacao_dos_clientes([cliente], completo=False)[0],
        "chave": chave_do_cliente(cliente),
        "consoles": consoles,
        **situacao_das_coletas(cliente, consoles),
        **contexto_relatorios(cliente),
        **contexto_agendamentos(cliente),
    }
    return render(request, "clientes/detalhe.html", contexto)


@exige(papeis.pode_editar_clientes)
@require_http_methods(["GET", "POST"])
def novo(request):
    form = ClienteForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        cliente = form.save()
        registrar(request, Acao.CLIENTE_CRIADO, cliente_id=cliente.pk, nome=cliente.nome)
        messages.success(request, f"Cliente {cliente.nome} cadastrado.")
        return redirect("clientes:detalhe", pk=cliente.pk)
    return render(request, "clientes/form.html", {"form": form, "titulo": "Novo cliente"})


@exige(papeis.pode_editar_clientes)
@require_http_methods(["GET", "POST"])
def editar(request, pk):
    cliente = _cliente_da_organizacao(pk)
    nome_antes = cliente.nome  # a validação do formulário já altera o objeto
    form = ClienteForm(request.POST or None, instance=cliente)
    if request.method == "POST" and form.is_valid():
        form.save()
        if cliente.nome != nome_antes:
            registrar(
                request,
                Acao.CLIENTE_ALTERADO,
                cliente_id=cliente.pk,
                nome_antes=nome_antes,
                nome_depois=cliente.nome,
            )
        messages.success(request, "Cliente atualizado.")
        return redirect("clientes:lista")
    return render(
        request, "clientes/form.html", {"form": form, "titulo": f"Editar {cliente.nome}"}
    )


@exige(papeis.pode_editar_clientes)
@require_http_methods(["GET", "POST"])
def apagar(request, pk):
    from conexoes.views import chave_do_cliente

    cliente = _cliente_da_organizacao(pk)
    chave = chave_do_cliente(cliente)
    if request.method == "POST":
        nome, cliente_id = cliente.nome, cliente.pk
        cliente.delete()  # a chave da UniFi do cliente vai junto
        registrar(
            request, Acao.CLIENTE_APAGADO, cliente_id=cliente_id, nome=nome, conexao_unifi=chave is not None
        )
        messages.success(request, f"Cliente {nome} apagado.")
        return redirect("clientes:lista")
    return render(request, "clientes/apagar.html", {"cliente": cliente, "chave": chave})
