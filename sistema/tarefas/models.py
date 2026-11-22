"""Fila de tarefas no PostgreSQL.

Tabela da plataforma (sem RLS): guarda só o tipo, os ids de organização e cliente e a
situação. Nunca guarda chave, senha nem dado coletado. Quem executa a tarefa entra no
contexto da organização dela, e aí a RLS vale como no site.
"""
from django.db import models
from django.utils import timezone


class Situacao(models.TextChoices):
    FILA = "fila", "Na fila"
    RODANDO = "rodando", "Rodando"
    FEITA = "feita", "Feita"
    FALHOU = "falhou", "Falhou"


class Tarefa(models.Model):
    tipo = models.CharField("tipo", max_length=50)
    organizacao = models.ForeignKey(
        "organizacoes.Organizacao", on_delete=models.CASCADE, null=True, blank=True,
        related_name="+", verbose_name="organização",
    )
    # Sem chave estrangeira: o cliente fica sob RLS e a fila é lida sem organização.
    cliente_id = models.BigIntegerField("cliente", null=True, blank=True)
    parametros = models.JSONField("parâmetros", default=dict, blank=True)
    # Evita duas tarefas iguais na fila ou rodando (ex.: "coletar_cliente:42").
    exclusiva = models.CharField("identificador exclusivo", max_length=100, null=True, blank=True)
    situacao = models.CharField("situação", max_length=10, choices=Situacao.choices, default=Situacao.FILA)
    tentativas = models.PositiveSmallIntegerField("tentativas", default=0)
    max_tentativas = models.PositiveSmallIntegerField("máximo de tentativas", default=3)
    executar_em = models.DateTimeField("executar a partir de", default=timezone.now)
    criada_em = models.DateTimeField("criada em", default=timezone.now)
    iniciada_em = models.DateTimeField("iniciada em", null=True, blank=True)
    terminada_em = models.DateTimeField("terminada em", null=True, blank=True)
    erro = models.CharField("erro", max_length=500, blank=True)
    pedida_por_id = models.BigIntegerField("pedida por (usuário)", null=True, blank=True)

    class Meta:
        verbose_name = "tarefa"
        verbose_name_plural = "tarefas"
        indexes = [models.Index(fields=["situacao", "executar_em"])]
        constraints = [
            models.UniqueConstraint(
                fields=["exclusiva"],
                condition=models.Q(situacao__in=["fila", "rodando"]),
                name="tarefa_exclusiva_ativa",
            ),
        ]

    def __str__(self):
        return f"{self.tipo} #{self.pk} ({self.situacao})"


class Periodica(models.Model):
    """Última vez que cada tarefa periódica foi disparada (vale para vários trabalhadores)."""

    nome = models.CharField("nome", max_length=50, unique=True)
    ultima_vez = models.DateTimeField("última vez", null=True, blank=True)

    class Meta:
        verbose_name = "tarefa periódica"
        verbose_name_plural = "tarefas periódicas"
