from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from contas.views import inicio, login_do_admin

# O admin do Django não tem login próprio: usa o mesmo login do sistema (com MFA).
admin.site.login = login_do_admin

urlpatterns = [
    path("", inicio, name="inicio"),
    path("contas/", include("allauth.urls")),
    path(settings.ADMIN_URL, admin.site.urls),
]
