from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from organizacoes import papeis
from organizacoes.permissoes import exige

from .forms import ClienteForm
from .models import Cliente


def _cliente_da_organizacao(pk):
    # Cliente.objects só enxerga a organização atual: de outra organização dá 404.
    return get_object_or_404(Cliente.objects, pk=pk)


@exige(papeis.pode_ver_clientes)
def lista(request):
    return render(request, "clientes/lista.html", {"clientes": Cliente.objects.all()})


@exige(papeis.pode_editar_clientes)
@require_http_methods(["GET", "POST"])
def novo(request):
    form = ClienteForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        cliente = form.save()
        messages.success(request, f"Cliente {cliente.nome} cadastrado.")
        return redirect("clientes:lista")
    return render(request, "clientes/form.html", {"form": form, "titulo": "Novo cliente"})


@exige(papeis.pode_editar_clientes)
@require_http_methods(["GET", "POST"])
def editar(request, pk):
    cliente = _cliente_da_organizacao(pk)
    form = ClienteForm(request.POST or None, instance=cliente)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Cliente atualizado.")
        return redirect("clientes:lista")
    return render(
        request, "clientes/form.html", {"form": form, "titulo": f"Editar {cliente.nome}"}
    )


@exige(papeis.pode_editar_clientes)
@require_http_methods(["GET", "POST"])
def apagar(request, pk):
    cliente = _cliente_da_organizacao(pk)
    if request.method == "POST":
        nome = cliente.nome
        cliente.delete()
        messages.success(request, f"Cliente {nome} apagado.")
        return redirect("clientes:lista")
    return render(request, "clientes/apagar.html", {"cliente": cliente})
