"""Esconde segredos nas páginas e relatórios de erro do Django.

O filtro padrão só esconde nomes em inglês (KEY, PASS, SECRET, TOKEN...). Aqui também
CHAVE, SENHA e CIFRAD (valores cifrados), em configurações e em campos de formulário.
"""
import re

from django.views.debug import SafeExceptionReporterFilter


class FiltroDeErros(SafeExceptionReporterFilter):
    hidden_settings = re.compile(
        "API|TOKEN|KEY|SECRET|PASS|SIGNATURE|HTTP_COOKIE|CHAVE|SENHA|CIFRAD", flags=re.I
    )

    def get_post_parameters(self, request):
        parametros = super().get_post_parameters(request)
        if request is None or not parametros:
            return parametros
        parametros = parametros.copy()
        for nome in parametros:
            if self.hidden_settings.search(nome):
                parametros[nome] = self.cleansed_substitute
        return parametros
