"""Conexão de cada cliente do MSP com a UniFi.

Cada cliente tem no máximo uma chave Site Manager (unifi.ui.com). A chave fica cifrada
(cofre/cifra.py); depois de salva, só os 4 últimos caracteres aparecem na tela.

Toda tabela daqui leva organização e cliente: a organização para o isolamento entre MSPs
(RLS), o cliente para o acesso só de leitura do cliente final, previsto para o futuro.
"""
from django.core.exceptions import PermissionDenied
from django.db import models
from django.utils import timezone

from cofre.cifra import cifrar, decifrar, ultimos4
from organizacoes.isolamento import ModeloDaOrganizacao


class ChaveUniFi(ModeloDaOrganizacao):
    CAMPOS_CIFRADOS = ["chave_cifrada"]

    cliente = models.OneToOneField(
        "clientes.Cliente",
        on_delete=models.CASCADE,
        related_name="chave_unifi",
        verbose_name="cliente",
    )
    chave_cifrada = models.TextField("chave cifrada", editable=False)
    final = models.CharField("últimos 4 caracteres", max_length=4, editable=False)
    cadastrada_em = models.DateTimeField("cadastrada em", default=timezone.now, editable=False)
    trocada_em = models.DateTimeField("trocada em", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "chave da UniFi"
        verbose_name_plural = "chaves da UniFi"

    def __str__(self):
        return f"Chave da UniFi de {self.cliente} (final {self.final})"

    def __repr__(self):
        return f"<ChaveUniFi cliente={self.cliente_id} final={self.final}>"

    def definir(self, chave):
        """Guarda uma chave nova (cifrada). Não grava no banco: chame save() depois."""
        if self.pk:
            self.trocada_em = timezone.now()
        self.chave_cifrada = cifrar(chave)
        self.final = ultimos4(chave)

    def abrir(self):
        """A chave em texto, só para chamar a UniFi. Nunca mostrar nem registrar."""
        return decifrar(self.chave_cifrada)

    def save(self, *args, **kwargs):
        # O cliente tem que ser da mesma organização (o banco também confere).
        self._conferir_organizacao()
        if self.cliente.organizacao_id != self.organizacao_id:
            raise PermissionDenied("Cliente de outra organização.")
        return super().save(*args, **kwargs)
