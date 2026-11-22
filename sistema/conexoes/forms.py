import re

from django import forms
from django.views.decorators.debug import sensitive_variables

FORMATO_CHAVE = re.compile(r"^[A-Za-z0-9._~-]{20,200}$")


class ChaveForm(forms.Form):
    chave = forms.CharField(
        label="Chave da API (Site Manager)",
        strip=True,
        # render_value=False: a chave nunca volta para a tela, nem quando há erro.
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off", "spellcheck": "false"}),
        help_text="Gere em unifi.ui.com, menu API. Depois de salva, só os 4 últimos caracteres aparecem.",
    )

    @sensitive_variables("chave")
    def clean_chave(self):
        chave = self.cleaned_data["chave"]
        if not FORMATO_CHAVE.match(chave):
            # Mensagem sem repetir o que foi digitado.
            raise forms.ValidationError(
                "Isso não parece uma chave da UniFi. Copie de novo a chave inteira, sem espaços."
            )
        return chave
