"""Marca de cada organização e relatórios gerados."""
from django.conf import settings
from django.db import models
from django.utils import timezone

from coletas.models import DoCliente
from organizacoes.isolamento import ModeloDaOrganizacao


class Tema(models.TextChoices):
    ESCURO = "escuro", "Escuro"
    CLARO = "claro", "Claro"


class Marca(ModeloDaOrganizacao):
    """Como o relatório se apresenta: nome e contato do MSP, logo e tema. Uma por organização."""

    empresa = models.CharField("nome da empresa", max_length=150)
    contato = models.CharField("contato", max_length=150, blank=True,
                               help_text="E-mail ou telefone que aparece no relatório.")
    tema = models.CharField("tema", max_length=10, choices=Tema.choices, default=Tema.ESCURO)
    # Logo já validado e regravado (PNG), pronto para entrar no relatório como imagem embutida.
    logo = models.BinaryField("logo", null=True, blank=True, editable=False)
    atualizada_em = models.DateTimeField("atualizada em", default=timezone.now)

    class Meta:
        verbose_name = "marca"
        verbose_name_plural = "marcas"
        constraints = [models.UniqueConstraint(fields=["organizacao"], name="marca_unica_na_organizacao")]

    def __str__(self):
        return self.empresa


class SituacaoRelatorio(models.TextChoices):
    GERANDO = "gerando", "Gerando"
    PRONTO = "pronto", "Pronto"
    FALHOU = "falhou", "Falhou"


class Origem(models.TextChoices):
    MANUAL = "manual", "Manual"
    AGENDADO = "agendado", "Agendado"


class Relatorio(DoCliente):
    """Um relatório gerado: período, quem pediu, o HTML, o PDF e a higiene da conta (só para o MSP)."""

    inicio = models.DateTimeField("início do período")
    fim = models.DateTimeField("fim do período")
    rotulo = models.CharField("período", max_length=60)
    situacao = models.CharField("situação", max_length=10, choices=SituacaoRelatorio.choices,
                                default=SituacaoRelatorio.GERANDO)
    pedido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+", verbose_name="pedido por")
    pedido_em = models.DateTimeField("pedido em", default=timezone.now)
    origem = models.CharField("origem", max_length=10, choices=Origem.choices, default=Origem.MANUAL)
    # Fica nulo se o agendamento for excluído; a origem continua dizendo que foi agendado.
    agendamento = models.ForeignKey("envios.Agendamento", on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name="agendamento")
    pronto_em = models.DateTimeField("pronto em", null=True, blank=True)
    html = models.TextField("HTML", blank=True)
    pdf = models.BinaryField("PDF", null=True, blank=True)
    higiene = models.JSONField("higiene da conta", default=list, blank=True)
    erro = models.CharField("erro", max_length=300, blank=True)

    class Meta:
        verbose_name = "relatório"
        verbose_name_plural = "relatórios"
        ordering = ["-pedido_em"]
        indexes = [models.Index(fields=["cliente", "-pedido_em"])]
