from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


class Organizacao(models.Model):
    """Um MSP. Criada pelo dono da plataforma no admin do Django."""

    nome = models.CharField("nome", max_length=150)
    ativa = models.BooleanField("ativa", default=True)
    criada_em = models.DateTimeField("criada em", default=timezone.now)

    class Meta:
        verbose_name = "organização"
        verbose_name_plural = "organizações"
        ordering = ["nome"]
        constraints = [
            models.UniqueConstraint(Lower("nome"), name="organizacao_nome_unico_sem_maiusculas"),
        ]

    def __str__(self):
        return self.nome


class Papel(models.TextChoices):
    ADMIN = "admin", "Admin"
    OPERADOR = "operador", "Operador"
    LEITURA = "leitura", "Leitura"


class Vinculo(models.Model):
    """Liga um usuário a uma organização, com um papel. No começo, um vínculo por usuário."""

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="vinculo",
        verbose_name="usuário",
    )
    organizacao = models.ForeignKey(
        Organizacao,
        on_delete=models.PROTECT,
        related_name="vinculos",
        verbose_name="organização",
    )
    papel = models.CharField("papel", max_length=20, choices=Papel.choices)
    criado_em = models.DateTimeField("criado em", default=timezone.now)

    class Meta:
        verbose_name = "vínculo"
        verbose_name_plural = "vínculos"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(papel__in=Papel.values), name="vinculo_papel_valido"
            ),
        ]

    def __str__(self):
        return f"{self.usuario} — {self.organizacao} ({self.get_papel_display()})"
