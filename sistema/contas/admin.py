from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from auditoria.models import Acao
from auditoria.registro import registrar

from .models import Usuario


class UsuarioCriacaoForm(UserCreationForm):
    class Meta:
        model = Usuario
        fields = ("email", "nome")


class UsuarioAlteracaoForm(UserChangeForm):
    class Meta:
        model = Usuario
        fields = ("email", "nome", "is_active", "is_staff", "is_superuser")


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    add_form = UsuarioCriacaoForm
    form = UsuarioAlteracaoForm
    ordering = ("email",)
    list_display = ("email", "nome", "is_active", "is_staff", "is_superuser")
    list_filter = ("is_active", "is_staff", "is_superuser")
    search_fields = ("email", "nome")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Dados", {"fields": ("nome",)}),
        ("Acesso", {"fields": ("is_active", "is_staff", "is_superuser")}),
        ("Datas", {"fields": ("last_login", "criado_em")}),
    )
    readonly_fields = ("last_login", "criado_em")
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "nome", "password1", "password2")}),
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        campos = [c for c in form.changed_data if c not in ("password", "password1", "password2")]
        if change and not campos:
            return
        # O dono não tem organização: estes eventos vão para a auditoria da plataforma.
        registrar(
            request,
            Acao.USUARIO_ALTERADO if change else Acao.USUARIO_CRIADO,
            alvo_id=obj.pk,
            alvo_email=obj.email,
            campos=campos,
        )

    def has_delete_permission(self, request, obj=None):
        # Para tirar o acesso, desative o usuário. A exclusão definitiva será um
        # processo próprio (LGPD), que também apaga o vínculo (protegido pela RLS).
        return False
