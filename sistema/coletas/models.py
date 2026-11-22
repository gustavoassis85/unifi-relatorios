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


class DoConsole(DoCliente):
    """Base das tabelas de dado coletado de um console."""

    console = models.ForeignKey(
        "conexoes.Console", on_delete=models.CASCADE, related_name="+", verbose_name="console"
    )
    coletado_em = models.DateTimeField("coletado em", default=timezone.now)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.console.cliente_id != self.cliente_id:
            raise PermissionDenied("Console de outro cliente.")
        return super().save(*args, **kwargs)


class ConsoleEstado(DoConsole):
    """Foto do console a cada coleta (Site Manager /v1/hosts). Dá a disponibilidade no mês."""

    nome = models.CharField(max_length=150, blank=True)
    modelo = models.CharField(max_length=100, blank=True)
    tipo = models.CharField(max_length=50, blank=True)            # console ou network-server
    conectado = models.BooleanField(default=False)
    estado = models.CharField(max_length=50, blank=True)          # valor original da API
    versao_os = models.CharField(max_length=50, blank=True)       # UniFi OS (só consoles)
    firmware = models.CharField(max_length=50, blank=True)        # versão que o Site Manager mostra
    versao_network = models.CharField(max_length=50, blank=True)
    atualizacao_disponivel = models.CharField(max_length=50, blank=True)
    ultimo_backup = models.DateTimeField(null=True, blank=True)
    mudou_estado_em = models.DateTimeField(null=True, blank=True)
    wans_conectadas = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "situação do console"
        verbose_name_plural = "situações dos consoles"
        constraints = [models.UniqueConstraint(fields=["console", "coletado_em"], name="console_estado_unico")]
        indexes = [models.Index(fields=["console", "-coletado_em"])]


class WanHora(DoConsole):
    """Métricas do link por hora (Site Manager /v1/isp-metrics/1h).

    Hora que não veio da API não tem linha: o relatório trata como possível
    indisponibilidade, nunca como 100%.
    """

    site_id = models.CharField("site (Site Manager)", max_length=100)
    horario = models.DateTimeField("início da hora")
    latencia_media = models.FloatField(null=True, blank=True)    # ms
    latencia_max = models.FloatField(null=True, blank=True)      # ms
    perda_pct = models.FloatField(null=True, blank=True)
    uptime_pct = models.FloatField(null=True, blank=True)
    downtime = models.FloatField(null=True, blank=True)
    download_kbps = models.BigIntegerField(null=True, blank=True)  # velocidade do plano, não tráfego
    upload_kbps = models.BigIntegerField(null=True, blank=True)
    provedor = models.CharField(max_length=150, blank=True)
    asn = models.CharField(max_length=50, blank=True)

    class Meta:
        verbose_name = "WAN por hora"
        verbose_name_plural = "WAN por hora"
        constraints = [models.UniqueConstraint(fields=["console", "site_id", "horario"], name="wan_hora_unica")]
        indexes = [models.Index(fields=["cliente", "horario"])]
