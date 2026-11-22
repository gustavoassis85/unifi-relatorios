from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .models import Acao
from .registro import registrar, registrar_para_usuario


@receiver(user_logged_in, dispatch_uid="auditoria_login")
def ao_entrar(sender, request, user, **kwargs):
    registrar_para_usuario(request, user, Acao.LOGIN)


@receiver(user_logged_out, dispatch_uid="auditoria_logout")
def ao_sair(sender, request, user, **kwargs):
    if user is not None:
        registrar_para_usuario(request, user, Acao.LOGOUT)


@receiver(user_login_failed, dispatch_uid="auditoria_login_falhou")
def ao_falhar(sender, credentials, request=None, **kwargs):
    # As credenciais chegam com a senha mascarada pelo Django; só o e-mail é usado.
    email = (credentials.get("email") or credentials.get("username") or "").strip().lower()[:254]
    usuario = get_user_model().objects.filter(email__iexact=email).first() if email else None
    if usuario is not None:
        registrar_para_usuario(request, usuario, Acao.LOGIN_FALHOU)
    else:
        registrar(request, Acao.LOGIN_FALHOU, email_digitado=email)
