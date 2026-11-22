"""Admin do Django: o dono da plataforma gerencia organizações e usuários.

O vínculo e os dados dos clientes dos MSPs não aparecem aqui. O primeiro admin
de cada organização é criado junto com ela, no mesmo formulário.
"""
from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

from auditoria.models import Acao
from auditoria.registro import registrar

from .isolamento import contexto
from .models import Organizacao
from .servicos import criar_organizacao_com_admin


class OrganizacaoCriacaoForm(forms.ModelForm):
    admin_email = forms.EmailField(label="E-mail do primeiro admin")
    admin_nome = forms.CharField(label="Nome do primeiro admin", max_length=150)
    admin_senha1 = forms.CharField(label="Senha inicial", widget=forms.PasswordInput, strip=False)
    admin_senha2 = forms.CharField(
        label="Confirme a senha", widget=forms.PasswordInput, strip=False
    )

    class Meta:
        model = Organizacao
        fields = ["nome"]

    def clean_admin_email(self):
        email = get_user_model().objects.normalizar_email(self.cleaned_data["admin_email"])
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Já existe um usuário com este e-mail.")
        return email

    def clean(self):
        dados = super().clean()
        senha1, senha2 = dados.get("admin_senha1"), dados.get("admin_senha2")
        if senha1 and senha2:
            if senha1 != senha2:
                self.add_error("admin_senha2", "As senhas não conferem.")
            else:
                try:
                    validate_password(senha1)
                except forms.ValidationError as erro:
                    self.add_error("admin_senha1", erro)
        return dados


@admin.register(Organizacao)
class OrganizacaoAdmin(admin.ModelAdmin):
    list_display = ("nome", "ativa", "criada_em")
    list_filter = ("ativa",)
    search_fields = ("nome",)
    readonly_fields = ("criada_em",)
    fields = ("nome", "ativa", "criada_em")
    add_fieldsets = (
        (None, {"fields": ("nome",)}),
        ("Primeiro admin", {"fields": ("admin_email", "admin_nome", "admin_senha1", "admin_senha2")}),
    )

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return self.add_fieldsets
        return super().get_fieldsets(request, obj)

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs["form"] = OrganizacaoCriacaoForm
        return super().get_form(request, obj, **kwargs)

    def save_model(self, request, obj, form, change):
        if change:
            super().save_model(request, obj, form, change)
            if form.changed_data:
                registrar(
                    request,
                    Acao.ORGANIZACAO_ALTERADA,
                    organizacao_id=obj.pk,
                    campos=form.changed_data,
                    ativa=obj.ativa,
                )
            return
        organizacao, admin_org = criar_organizacao_com_admin(
            nome=form.cleaned_data["nome"],
            admin_email=form.cleaned_data["admin_email"],
            admin_nome=form.cleaned_data["admin_nome"],
            admin_senha=form.cleaned_data["admin_senha1"],
        )
        registrar(
            request, Acao.ORGANIZACAO_CRIADA, organizacao_id=organizacao.pk, nome=organizacao.nome
        )
        # O primeiro admin também aparece na auditoria da própria organização.
        with contexto(organizacao_id=organizacao.pk):
            registrar(
                request,
                Acao.USUARIO_CRIADO,
                alvo_id=admin_org.pk,
                alvo_email=admin_org.email,
                papel="admin",
            )
        # O admin do Django continua usando o objeto que ele já tem em mãos.
        obj.pk = organizacao.pk
        obj.criada_em = organizacao.criada_em

    def has_delete_permission(self, request, obj=None):
        # Apagar um MSP vai ser um processo próprio (LGPD), não um botão do admin.
        return False
