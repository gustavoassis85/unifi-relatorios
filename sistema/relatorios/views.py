from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from auditoria.models import Acao
from auditoria.registro import registrar
from organizacoes import papeis
from organizacoes.permissoes import exige

from .forms import MarcaForm
from .servicos import logo_embutido, marca_da_organizacao


@exige(papeis.pode_editar_marca)
@require_http_methods(["GET", "POST"])
def marca(request):
    atual = marca_da_organizacao()
    form = MarcaForm(request.POST or None, request.FILES or None, instance=atual)
    if request.method == "POST" and form.is_valid():
        salva = form.save(commit=False)
        salva.atualizada_em = timezone.now()
        salva.save()
        registrar(request, Acao.MARCA_ALTERADA, empresa=salva.empresa, tema=salva.tema, logo=bool(salva.logo))
        messages.success(request, "Marca salva. Os próximos relatórios já saem com ela.")
        return redirect("relatorios:marca")
    return render(request, "relatorios/marca.html", {"form": form, "marca": atual, "logo": logo_embutido(atual)})
