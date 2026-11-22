from django.apps import AppConfig


class ColetasConfig(AppConfig):
    name = "coletas"
    verbose_name = "Coletas"

    def ready(self):
        from . import coletores, retencao, tarefas  # noqa: F401  (registra tarefa, periódicas e partes)
