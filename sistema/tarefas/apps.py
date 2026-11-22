from django.apps import AppConfig


class TarefasConfig(AppConfig):
    name = "tarefas"
    verbose_name = "Tarefas em segundo plano"

    def ready(self):
        from . import manutencao  # noqa: F401  (registra as periódicas da fila)
