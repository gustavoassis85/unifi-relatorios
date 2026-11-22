from django.apps import AppConfig


class RelatoriosConfig(AppConfig):
    name = "relatorios"
    verbose_name = "Relatórios"

    def ready(self):
        from . import tarefas  # noqa: F401  (registra a tarefa de geração e a limpeza)
