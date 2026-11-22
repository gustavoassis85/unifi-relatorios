from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from auditoria.models import Acao
from auditoria.registro import registrar
from organizacoes import papeis
from organizacoes.permissoes import exige

from .forms import SmtpForm
from .models import ConfigSmtp
from .tarefas import enfileirar_teste


def _config():
    return ConfigSmtp.objects.first()


@sensitive_post_parameters("senha")
@exige(papeis.pode_configurar_smtp)
@require_http_methods(["GET", "POST"])
def smtp(request):
    atual = _config()
    form = SmtpForm(request.POST or None, instance=atual)
    if request.method == "POST" and form.is_valid():
        salvo = form.save(commit=False)
        salvo.atualizado_em = timezone.now()
        salvo.save()
        registrar(request, Acao.SMTP_ALTERADO, servidor=salvo.servidor, porta=salvo.porta,
                  seguranca=salvo.seguranca, ativo=salvo.ativo, credencial_trocada=form.senha_trocada)
        messages.success(request, "Servidor de e-mail salvo. Use \"Enviar teste\" para conferir.")
        return redirect("envios:smtp")
    return render(request, "envios/smtp.html", {"form": form, "config": atual})


@exige(papeis.pode_configurar_smtp)
@require_http_methods(["POST"])
def testar(request):
    config = _config()
    if config is None:
        messages.error(request, "Salve o servidor de e-mail antes de testar.")
        return redirect("envios:smtp")
    if enfileirar_teste(config, request.user) is not None:
        config.teste_pedido_em = timezone.now()
        config.save(update_fields=["teste_pedido_em"])
        registrar(request, Acao.SMTP_TESTADO, servidor=config.servidor, porta=config.porta)
    return redirect("envios:smtp")


@exige(papeis.pode_configurar_smtp)
@require_http_methods(["GET"])
def situacao_teste(request):
    return render(request, "envios/_teste_smtp.html", {"config": _config()})
