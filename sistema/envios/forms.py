from django import forms

from .models import ConfigSmtp
from .rede import eh_ip_literal_interno


class SmtpForm(forms.ModelForm):
    senha = forms.CharField(
        label="Senha", required=False, strip=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        help_text="Em branco mantém a senha atual. No Gmail, use uma senha de app.",
    )
    apagar_senha = forms.BooleanField(label="Apagar a senha guardada", required=False)

    class Meta:
        model = ConfigSmtp
        fields = ["ativo", "servidor", "porta", "seguranca", "usuario", "remetente"]

    def clean_servidor(self):
        servidor = self.cleaned_data["servidor"].strip().lower().rstrip(".")
        if not servidor or any(c.isspace() for c in servidor) or "/" in servidor or ":" in servidor.strip("[]"):
            raise forms.ValidationError("Informe só o nome do servidor, sem http:// nem porta. Exemplo: smtp.gmail.com")
        if eh_ip_literal_interno(servidor):
            raise forms.ValidationError("O servidor de e-mail não pode ser um endereço da rede interna.")
        return servidor

    def clean_usuario(self):
        return self.cleaned_data["usuario"].strip()

    def clean(self):
        dados = super().clean()
        tem_senha = bool(dados.get("senha")) or (bool(self.instance.senha_cifrada) and not dados.get("apagar_senha"))
        if dados.get("usuario") and not tem_senha:
            self.add_error("senha", "Com usuário, informe também a senha.")
        return dados

    def save(self, commit=True):
        config = super().save(commit=False)
        if self.cleaned_data.get("senha"):
            config.definir_senha(self.cleaned_data["senha"])
        elif self.cleaned_data.get("apagar_senha") or not config.usuario:
            config.definir_senha("")
        if commit:
            config.save()
        return config

    @property
    def senha_trocada(self):
        return bool(self.cleaned_data.get("senha")) or bool(self.cleaned_data.get("apagar_senha"))
