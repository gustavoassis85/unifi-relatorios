from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from auditoria.models import Acao
from auditoria.registro import registrar
from clientes.models import Cliente
from organizacoes import papeis
from organizacoes.permissoes import exige

from .forms import ChaveForm
from .models import ChaveUniFi


def chave_do_cliente(cliente):
    # Sempre pelo gerenciador filtrado pela organização (nunca pelo acesso reverso).
    return ChaveUniFi.objects.filter(cliente=cliente).first()


@exige(papeis.pode_gerenciar_chaves)
@sensitive_post_parameters("chave")
@require_http_methods(["GET", "POST"])
def salvar(request, pk):
    cliente = get_object_or_404(Cliente.objects, pk=pk)
    chave = chave_do_cliente(cliente)
    form = ChaveForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        nova = chave is None
        if nova:
            chave = ChaveUniFi(cliente=cliente)
        chave.definir(form.cleaned_data["chave"])
        chave.save()
        registrar(
            request,
            Acao.CHAVE_CADASTRADA if nova else Acao.CHAVE_TROCADA,
            cliente_id=cliente.pk,
            cliente=cliente.nome,
            final=chave.final,
        )
        messages.success(request, "Chave salva." if nova else "Chave trocada.")
        return redirect("clientes:detalhe", pk=cliente.pk)
    titulo = f"Trocar a chave da UniFi de {cliente.nome}" if chave else f"Cadastrar a chave da UniFi de {cliente.nome}"
    return render(
        request, "conexoes/chave_form.html", {"form": form, "cliente": cliente, "chave": chave, "titulo": titulo}
    )


@exige(papeis.pode_gerenciar_chaves)
@require_http_methods(["GET", "POST"])
def apagar(request, pk):
    cliente = get_object_or_404(Cliente.objects, pk=pk)
    chave = chave_do_cliente(cliente)
    if chave is None:
        return redirect("clientes:detalhe", pk=cliente.pk)
    if request.method == "POST":
        final = chave.final
        chave.delete()
        registrar(request, Acao.CHAVE_APAGADA, cliente_id=cliente.pk, cliente=cliente.nome, final=final)
        messages.success(request, f"Chave de {cliente.nome} apagada.")
        return redirect("clientes:detalhe", pk=cliente.pk)
    return render(request, "conexoes/chave_apagar.html", {"cliente": cliente, "chave": chave})
