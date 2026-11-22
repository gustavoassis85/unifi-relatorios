"""Marca de cada organização e relatórios gerados."""
from django.db import models
from django.utils import timezone

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
