from django import forms

from .models import Cliente


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ["nome"]

    def clean_nome(self):
        nome = " ".join(self.cleaned_data["nome"].split())
        # Cliente.objects já olha só a organização atual.
        repetido = Cliente.objects.filter(nome__iexact=nome).exclude(pk=self.instance.pk)
        if repetido.exists():
            raise forms.ValidationError("Já existe um cliente com este nome.")
        return nome
