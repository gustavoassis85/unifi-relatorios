from django.apps import AppConfig


class ColetasConfig(AppConfig):
    name = "coletas"
    verbose_name = "Coletas"

    def ready(self):
        from . import coletores, tarefas  # noqa: F401  (registra a tarefa, a periódica e as partes)
