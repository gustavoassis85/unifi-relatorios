from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from organizacoes.isolamento import ModeloDaOrganizacao


class Cliente(ModeloDaOrganizacao):
    """Cliente de um MSP. Por enquanto só o nome. Fica fora do admin do Django."""

    nome = models.CharField("nome", max_length=150)
    criado_em = models.DateTimeField("criado em", default=timezone.now)

    class Meta:
        verbose_name = "cliente"
        verbose_name_plural = "clientes"
        ordering = ["nome"]
        constraints = [
            models.UniqueConstraint(
                "organizacao", Lower("nome"), name="cliente_nome_unico_na_organizacao"
            ),
            # Alvo das chaves estrangeiras compostas (organização + cliente) das tabelas
            # que pertencem a um cliente: o banco garante que são da mesma organização.
            models.UniqueConstraint(fields=["organizacao", "id"], name="cliente_organizacao_id"),
        ]

    def __str__(self):
        return self.nome
