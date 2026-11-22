from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse

from organizacoes.contexto import papel_da_requisicao

from .mfa import exige_mfa, tem_mfa

# Telas liberadas para quem ainda precisa configurar o MFA.
ROTAS_LIBERADAS = (
    "mfa_activate_totp",
    "mfa_view_recovery_codes",
    "mfa_download_recovery_codes",
    "account_logout",
    "account_reauthenticate",
)


class MfaObrigatorioMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        usuario = request.user
        if usuario.is_authenticated and exige_mfa(usuario, papel_da_requisicao(request)):
            if not tem_mfa(usuario) and not self._liberada(request.path):
                return redirect("mfa_activate_totp")
        return self.get_response(request)

    @staticmethod
    def _liberada(caminho):
        if caminho.startswith("/" + settings.STATIC_URL.lstrip("/")):
            return True
        return any(caminho == reverse(nome) for nome in ROTAS_LIBERADAS)
