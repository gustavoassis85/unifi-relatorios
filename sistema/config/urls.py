from django.conf import settings
from django.contrib import admin
from django.http import Http404
from django.urls import include, path

from contas.views import inicio, login_do_admin

# O admin do Django não tem login próprio: usa o mesmo login do sistema (com MFA).
admin.site.login = login_do_admin


def desativada(request, *args, **kwargs):
    raise Http404


urlpatterns = [
    path("", inicio, name="inicio"),
    path("clientes/", include("clientes.urls")),
    path("clientes/", include("conexoes.urls")),
    path("clientes/", include("coletas.urls")),
    path("usuarios/", include("organizacoes.urls")),
    path("relatorios/", include("relatorios.urls")),
    # O e-mail é o login e quem o define é o admin da organização: o usuário não
    # troca nem acrescenta e-mails por conta própria.
    path("contas/email/", desativada),
    path("contas/phone/", desativada),
    path("contas/", include("allauth.urls")),
    path(settings.ADMIN_URL, admin.site.urls),
]
