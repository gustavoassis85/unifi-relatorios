from django.contrib import messages
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from auditoria.models import Acao
from auditoria.registro import registrar

from . import papeis
from .forms import EMAIL_RECUSADO, EditarUsuarioForm, NovoUsuarioForm
from .permissoes import exige
from .servicos import criar_usuario_na_organizacao, vinculos_da_organizacao


@exige(papeis.pode_gerenciar_usuarios)
def lista(request):
    vinculos = vinculos_da_organizacao().order_by("usuario__email")
    return render(request, "organizacoes/usuarios_lista.html", {"vinculos": vinculos})


@exige(papeis.pode_gerenciar_usuarios)
@require_http_methods(["GET", "POST"])
def novo(request):
    form = NovoUsuarioForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        dados = form.cleaned_data
        try:
            with transaction.atomic():
                usuario = criar_usuario_na_organizacao(
                    request.vinculo.organizacao,
                    dados["email"],
                    dados["nome"],
                    dados["senha1"],
                    dados["papel"],
                )
                registrar(
                    request,
                    Acao.USUARIO_CRIADO,
                    alvo_id=usuario.pk,
                    alvo_email=usuario.email,
                    papel=dados["papel"],
                )
        except IntegrityError:
            # Corrida: o e-mail foi cadastrado entre a checagem e a gravação.
            form.add_error("email", EMAIL_RECUSADO)
        else:
            messages.success(request, f"Usuário {usuario.email} cadastrado.")
            return redirect("usuarios:lista")
    return render(request, "organizacoes/usuario_novo.html", {"form": form})


@exige(papeis.pode_gerenciar_usuarios)
@require_http_methods(["GET", "POST"])
def editar(request, usuario_id):
    # Parte do vínculo da organização atual: usuário de outra organização dá 404.
    vinculo = get_object_or_404(vinculos_da_organizacao(), usuario_id=usuario_id)
    proprio = vinculo.usuario_id == request.user.pk
    form = EditarUsuarioForm(request.POST or None, vinculo=vinculo, proprio=proprio)
    if request.method == "POST" and form.is_valid():
        usuario = vinculo.usuario
        antes = {"papel": vinculo.papel, "ativo": usuario.is_active}
        vinculo.papel = form.cleaned_data["papel"]
        vinculo.save(update_fields=["papel"])
        usuario.is_active = form.cleaned_data["ativo"]
        usuario.save(update_fields=["is_active"])
        depois = {"papel": vinculo.papel, "ativo": usuario.is_active}
        if antes != depois:
            registrar(
                request,
                Acao.USUARIO_ALTERADO,
                alvo_id=usuario.pk,
                alvo_email=usuario.email,
                antes=antes,
                depois=depois,
            )
        messages.success(request, f"Usuário {usuario.email} atualizado.")
        return redirect("usuarios:lista")
    return render(
        request,
        "organizacoes/usuario_editar.html",
        {"form": form, "vinculo": vinculo, "proprio": proprio},
    )
