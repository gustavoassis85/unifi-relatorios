"""Dados coletados da UniFi. Toda tabela leva organização (RLS) e cliente (acesso futuro do cliente)."""
from django.core.exceptions import PermissionDenied
from django.db import models
from django.utils import timezone

from organizacoes.isolamento import ModeloDaOrganizacao


class DoCliente(ModeloDaOrganizacao):
    """Base das tabelas que pertencem a um cliente."""

    cliente = models.ForeignKey(
        "clientes.Cliente", on_delete=models.CASCADE, related_name="+", verbose_name="cliente"
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self._conferir_organizacao()
        if self.cliente.organizacao_id != self.organizacao_id:
            raise PermissionDenied("Cliente de outra organização.")
        return super().save(*args, **kwargs)


class ResultadoExecucao(models.TextChoices):
    RODANDO = "rodando", "Rodando"
    OK = "ok", "Tudo certo"
    PARCIAL = "parcial", "Parte falhou"
    FALHOU = "falhou", "Falhou"


class ExecucaoColeta(DoCliente):
    """Uma rodada de coleta de um cliente: quando, de onde veio e o resultado de cada parte."""

    tarefa_id = models.BigIntegerField("tarefa", null=True, blank=True)
    automatica = models.BooleanField("automática", default=True)
    iniciada_em = models.DateTimeField("iniciada em", default=timezone.now)
    terminada_em = models.DateTimeField("terminada em", null=True, blank=True)
    resultado = models.CharField(
        "resultado", max_length=10, choices=ResultadoExecucao.choices, default=ResultadoExecucao.RODANDO
    )
    # [{"nome": "Consoles", "ok": true, "mensagem": "2 console(s)"}, ...]
    partes = models.JSONField("partes", default=list, blank=True)

    class Meta:
        verbose_name = "execução de coleta"
        verbose_name_plural = "execuções de coleta"
        ordering = ["-iniciada_em"]
        indexes = [models.Index(fields=["cliente", "-iniciada_em"])]
