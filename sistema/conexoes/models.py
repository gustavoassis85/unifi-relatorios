"""Conexão de cada cliente do MSP com a UniFi.

Cada cliente tem no máximo uma chave Site Manager (unifi.ui.com). A chave fica cifrada
(cofre/cifra.py); depois de salva, só os 4 últimos caracteres aparecem na tela.

Toda tabela daqui leva organização e cliente: a organização para o isolamento entre MSPs
(RLS), o cliente para o acesso só de leitura do cliente final, previsto para o futuro.
"""
from datetime import timedelta

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
    teste_pedido_em = models.DateTimeField("teste pedido em", null=True, blank=True, editable=False)
    testada_em = models.DateTimeField("último teste em", null=True, blank=True, editable=False)
    teste_ok = models.BooleanField("último teste funcionou", null=True, editable=False)
    teste_resultado = models.CharField("resultado do último teste", max_length=300, blank=True, editable=False)

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

    @property
    def teste_pendente(self):
        # Pedido há mais de 10 min sem resposta: o trabalhador está desligado; a tela para de esperar.
        if not self.teste_pedido_em or self.teste_pedido_em < timezone.now() - timedelta(minutes=10):
            return False
        return self.testada_em is None or self.testada_em < self.teste_pedido_em

    def abrir(self):
        """A chave em texto, só para chamar a UniFi. Nunca mostrar nem registrar."""
        return decifrar(self.chave_cifrada)

    def save(self, *args, **kwargs):
        # O cliente tem que ser da mesma organização (o banco também confere).
        self._conferir_organizacao()
        if self.cliente.organizacao_id != self.organizacao_id:
            raise PermissionDenied("Cliente de outra organização.")
        return super().save(*args, **kwargs)


class Console(ModeloDaOrganizacao):
    """Console que a chave do cliente enxerga no /v1/hosts.

    Nunca é apagado quando some da conta (o histórico das próximas etapas depende dele):
    fica marcado como "não aparece mais na conta". Só sai junto com o cliente.
    """

    cliente = models.ForeignKey(
        "clientes.Cliente", on_delete=models.CASCADE, related_name="consoles", verbose_name="cliente"
    )
    host_id = models.CharField("hostId", max_length=200)
    nome = models.CharField("nome", max_length=150, blank=True)
    modelo = models.CharField("modelo", max_length=100, blank=True)
    tipo = models.CharField("tipo", max_length=50, blank=True)
    conectado = models.BooleanField("conectado", default=False)
    firmware = models.CharField("firmware", max_length=50, blank=True)
    versao_network = models.CharField("versão do Network", max_length=50, blank=True)
    acompanhar = models.BooleanField("acompanhar", default=False)
    na_conta = models.BooleanField("aparece na conta", default=True)
    primeiro_visto_em = models.DateTimeField("visto pela primeira vez em", default=timezone.now)
    visto_em = models.DateTimeField("visto na conta pela última vez em", default=timezone.now)

    class Meta:
        verbose_name = "console"
        verbose_name_plural = "consoles"
        ordering = ["-na_conta", "-conectado", "nome"]
        constraints = [
            models.UniqueConstraint(fields=["cliente", "host_id"], name="console_unico_no_cliente"),
            # Alvo das chaves estrangeiras compostas (cliente + console) dos dados coletados.
            models.UniqueConstraint(fields=["cliente", "id"], name="console_cliente_id"),
            # O mesmo console não pode ser acompanhado por dois clientes da mesma organização.
            models.UniqueConstraint(
                fields=["organizacao", "host_id"],
                condition=models.Q(acompanhar=True),
                name="console_acompanhado_uma_vez_na_organizacao",
            ),
        ]

    def __str__(self):
        return self.nome or self.host_id

    @property
    def situacao(self):
        if not self.na_conta:
            return "Não aparece mais na conta"
        return "Conectado" if self.conectado else "Desconectado"

    def save(self, *args, **kwargs):
        self._conferir_organizacao()
        if self.cliente.organizacao_id != self.organizacao_id:
            raise PermissionDenied("Cliente de outra organização.")
        return super().save(*args, **kwargs)
