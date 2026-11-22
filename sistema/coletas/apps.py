from django.apps import AppConfig


class ColetasConfig(AppConfig):
    name = "coletas"
    verbose_name = "Coletas"

    def ready(self):
        from . import tarefas  # noqa: F401  (registra a tarefa de coleta e a periódica)
