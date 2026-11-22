from django.apps import AppConfig
from django.db.models.signals import post_migrate


class ContasConfig(AppConfig):
    name = "contas"
    verbose_name = "Contas"

    def ready(self):
        from config.banco import aplicar_permissoes

        # Uma vez por migração (dispatch_uid evita repetir para cada app).
        post_migrate.connect(aplicar_permissoes, dispatch_uid="aplicar_permissoes_banco")
