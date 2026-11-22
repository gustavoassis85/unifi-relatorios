import re

from django import forms
from django.core.validators import EmailValidator

from .agenda import proxima
from .models import MAX_AGENDAMENTOS_POR_CLIENTE, MAX_DESTINATARIOS, Agendamento, ConfigSmtp, Frequencia
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


class AgendamentoForm(forms.ModelForm):
    destinatarios_texto = forms.CharField(
        label="Destinatários", required=False,
        widget=forms.Textarea(attrs={"rows": 4, "autocomplete": "off"}),
        help_text=f"Um e-mail por linha (até {MAX_DESTINATARIOS}). Sem destinatários, o relatório só é "
                  "gerado e fica no histórico.",
    )

    class Meta:
        model = Agendamento
        fields = ["frequencia", "dia_do_mes", "dia_da_semana", "hora"]
        help_texts = {"dia_do_mes": "Só para o mensal. Até o dia 28, para existir em todos os meses.",
                      "dia_da_semana": "Só para o semanal."}

    def __init__(self, *args, cliente, **kwargs):
        super().__init__(*args, **kwargs)
        self.cliente = cliente
        if self.instance.pk:
            self.initial["destinatarios_texto"] = "\n".join(self.instance.destinatarios)
        elif not self.is_bound:
            self.initial.setdefault("dia_do_mes", 1)
            self.initial.setdefault("dia_da_semana", 0)

    def clean_destinatarios_texto(self):
        validar = EmailValidator(message="")
        lista, invalidos = [], []
        for item in re.split(r"[\s,;]+", self.cleaned_data["destinatarios_texto"]):
            if not item:
                continue
            try:
                validar(item)
            except forms.ValidationError:
                invalidos.append(item[:60])
                continue
            if item.lower() not in (e.lower() for e in lista):
                lista.append(item)
        if invalidos:
            raise forms.ValidationError("E-mail inválido: " + ", ".join(invalidos))
        if len(lista) > MAX_DESTINATARIOS:
            raise forms.ValidationError(f"No máximo {MAX_DESTINATARIOS} destinatários.")
        return lista

    def clean(self):
        dados = super().clean()
        frequencia = dados.get("frequencia")
        if frequencia == Frequencia.MENSAL and not dados.get("dia_do_mes"):
            self.add_error("dia_do_mes", "Escolha o dia do mês.")
        if frequencia == Frequencia.SEMANAL and dados.get("dia_da_semana") is None:
            self.add_error("dia_da_semana", "Escolha o dia da semana.")
        if not self.instance.pk:
            existentes = Agendamento.objects.filter(cliente=self.cliente).count()
            if existentes >= MAX_AGENDAMENTOS_POR_CLIENTE:
                raise forms.ValidationError(
                    f"Este cliente já tem {MAX_AGENDAMENTOS_POR_CLIENTE} agendamentos; edite ou exclua um deles.")
        return dados

    def save(self, commit=True):
        agendamento = super().save(commit=False)
        agendamento.cliente = self.cliente
        agendamento.destinatarios = self.cleaned_data["destinatarios_texto"]
        if agendamento.frequencia == Frequencia.MENSAL:
            agendamento.dia_da_semana = None
        else:
            agendamento.dia_do_mes = None
        agendamento.proxima_execucao = proxima(agendamento) if agendamento.ativo else None
        if commit:
            agendamento.save()
        return agendamento
