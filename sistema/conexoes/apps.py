from django.apps import AppConfig


class ConexoesConfig(AppConfig):
    name = "conexoes"
    verbose_name = "Conexões com a UniFi"

    def ready(self):
        from cofre.registro import registrar

        from .models import ChaveUniFi

        registrar(ChaveUniFi)  # entra na troca da chave mestra
