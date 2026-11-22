from django.apps import AppConfig


class EnviosConfig(AppConfig):
    name = "envios"
    verbose_name = "Envios por e-mail"

    def ready(self):
        from cofre.registro import registrar

        from . import disparo, tarefas  # noqa: F401  (registra a periódica e as tarefas de e-mail)
        from .models import ConfigSmtp

        registrar(ConfigSmtp)  # entra na troca da chave mestra
