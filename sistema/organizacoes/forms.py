from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

from .models import Papel

# Mesma mensagem para qualquer problema com o e-mail: não revela se ele já existe
# (em outra organização ou na plataforma).
EMAIL_RECUSADO = "Não foi possível cadastrar este e-mail. Confira o endereço ou use outro."


class NovoUsuarioForm(forms.Form):
    email = forms.EmailField(label="E-mail")
    nome = forms.CharField(label="Nome", max_length=150)
    papel = forms.ChoiceField(label="Papel", choices=Papel.choices, initial=Papel.LEITURA)
    senha1 = forms.CharField(label="Senha inicial", widget=forms.PasswordInput, strip=False)
    senha2 = forms.CharField(label="Confirme a senha", widget=forms.PasswordInput, strip=False)

    def clean_email(self):
        email = get_user_model().objects.normalizar_email(self.cleaned_data["email"])
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(EMAIL_RECUSADO)
        return email

    def clean(self):
        dados = super().clean()
        senha1, senha2 = dados.get("senha1"), dados.get("senha2")
        if senha1 and senha2:
            if senha1 != senha2:
                self.add_error("senha2", "As senhas não conferem.")
            else:
                try:
                    validate_password(senha1)
                except forms.ValidationError as erro:
                    self.add_error("senha1", erro)
        return dados


class EditarUsuarioForm(forms.Form):
    papel = forms.ChoiceField(label="Papel", choices=Papel.choices)
    ativo = forms.BooleanField(label="Ativo", required=False)

    def __init__(self, *args, vinculo, proprio, **kwargs):
        self.vinculo = vinculo
        self.proprio = proprio
        kwargs.setdefault(
            "initial", {"papel": vinculo.papel, "ativo": vinculo.usuario.is_active}
        )
        super().__init__(*args, **kwargs)

    def clean(self):
        dados = super().clean()
        if self.proprio and (
            dados.get("papel") != self.vinculo.papel or not dados.get("ativo")
        ):
            # Evita uma organização ficar sem admin por engano.
            raise forms.ValidationError("Você não pode mudar o próprio papel nem se desativar.")
        return dados
