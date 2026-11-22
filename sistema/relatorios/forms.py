from django import forms

from .logo import LogoInvalido, preparar_logo
from .models import Marca


class MarcaForm(forms.ModelForm):
    logo_arquivo = forms.FileField(
        label="Logo", required=False,
        help_text="PNG ou JPG, até 500 KB. A imagem é reduzida para caber em 600 x 200 pixels.",
        widget=forms.ClearableFileInput(attrs={"accept": "image/png,image/jpeg"}),
    )
    remover_logo = forms.BooleanField(label="Remover o logo atual", required=False)

    class Meta:
        model = Marca
        fields = ["empresa", "contato", "tema"]

    def clean_empresa(self):
        return " ".join(self.cleaned_data["empresa"].split())

    def clean_logo_arquivo(self):
        arquivo = self.cleaned_data.get("logo_arquivo")
        if not arquivo:
            return None
        try:
            return preparar_logo(arquivo)
        except LogoInvalido as erro:
            raise forms.ValidationError(str(erro)) from None

    def save(self, commit=True):
        marca = super().save(commit=False)
        if self.cleaned_data.get("remover_logo"):
            marca.logo = None
        if self.cleaned_data.get("logo_arquivo"):
            marca.logo = self.cleaned_data["logo_arquivo"]
        if commit:
            marca.save()
        return marca
