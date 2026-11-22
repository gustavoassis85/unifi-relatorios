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


# Equipamentos (connector, API oficial do Network) ------------------------------------

class SiteNetwork(DoConsole):
    """Site visto pela API Network (id em UUID, diferente do siteId da Site Manager)."""

    site_id = models.CharField(max_length=100)
    nome = models.CharField(max_length=150, blank=True)
    referencia = models.CharField(max_length=100, blank=True)   # internalReference (ex.: default)

    class Meta:
        verbose_name = "site do Network"
        verbose_name_plural = "sites do Network"
        constraints = [models.UniqueConstraint(fields=["console", "site_id"], name="site_network_unico")]


class ClientesAmostra(DoConsole):
    """Quantidade de clientes conectados por site, a cada coleta."""

    site_id = models.CharField(max_length=100)
    total = models.PositiveIntegerField(default=0)
    cabo = models.PositiveIntegerField(default=0)
    wifi = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "amostra de clientes conectados"
        verbose_name_plural = "amostras de clientes conectados"
        constraints = [
            models.UniqueConstraint(fields=["console", "site_id", "coletado_em"], name="clientes_amostra_unica")
        ]


class EquipamentoAmostra(DoConsole):
    """Foto de cada equipamento UniFi a cada coleta (estado, firmware, saúde, uplink, configuração)."""

    site_id = models.CharField(max_length=100)
    device_id = models.CharField(max_length=100)
    nome = models.CharField(max_length=150, blank=True)
    modelo = models.CharField(max_length=100, blank=True)
    mac = models.CharField(max_length=50, blank=True)
    ip = models.CharField(max_length=50, blank=True)
    estado = models.CharField(max_length=30, blank=True)          # ONLINE, OFFLINE...
    firmware = models.CharField(max_length=50, blank=True)
    firmware_atualizavel = models.BooleanField(null=True, blank=True)
    uptime_seg = models.BigIntegerField(null=True, blank=True)
    cpu_pct = models.FloatField(null=True, blank=True)
    memoria_pct = models.FloatField(null=True, blank=True)
    carga_1min = models.FloatField(null=True, blank=True)
    uplink_tx_bps = models.BigIntegerField(null=True, blank=True)  # taxa no momento, não volume
    uplink_rx_bps = models.BigIntegerField(null=True, blank=True)
    configuracao_id = models.CharField(max_length=100, blank=True)
    provisionado_em = models.DateTimeField(null=True, blank=True)  # último envio de configuração

    class Meta:
        verbose_name = "amostra de equipamento"
        verbose_name_plural = "amostras de equipamentos"
        constraints = [
            models.UniqueConstraint(fields=["console", "device_id", "coletado_em"], name="equipamento_amostra_unica")
        ]
        indexes = [models.Index(fields=["cliente", "coletado_em"])]


class RadioAmostra(DoConsole):
    """Retransmissão de cada rádio a cada coleta (statistics/latest)."""

    device_id = models.CharField(max_length=100)
    posicao = models.PositiveSmallIntegerField()
    frequencia_ghz = models.FloatField(null=True, blank=True)
    retransmissao_pct = models.FloatField(null=True, blank=True)

    class Meta:
        verbose_name = "amostra de rádio"
        verbose_name_plural = "amostras de rádios"
        constraints = [
            models.UniqueConstraint(fields=["console", "device_id", "coletado_em", "posicao"], name="radio_amostra_unica")
        ]


class RadioConfig(DoConsole):
    """Configuração de cada rádio a cada coleta (padrão, canal, largura)."""

    device_id = models.CharField(max_length=100)
    posicao = models.PositiveSmallIntegerField()
    frequencia_ghz = models.FloatField(null=True, blank=True)
    padrao = models.CharField(max_length=30, blank=True)          # 802.11ax...
    largura_mhz = models.PositiveIntegerField(null=True, blank=True)
    canal = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "configuração de rádio"
        verbose_name_plural = "configurações de rádios"
        constraints = [
            models.UniqueConstraint(fields=["console", "device_id", "coletado_em", "posicao"], name="radio_config_unica")
        ]


class PortaEstado(DoConsole):
    """Cada porta a cada coleta. Uma foto só engana (PC em repouso negocia 10/100 Mbps):
    a regra de porta abaixo da capacidade usa várias amostras."""

    device_id = models.CharField(max_length=100)
    idx = models.PositiveIntegerField()
    estado = models.CharField(max_length=20, blank=True)          # UP ou DOWN
    conector = models.CharField(max_length=30, blank=True)
    velocidade_mbps = models.PositiveIntegerField(null=True, blank=True)
    velocidade_max_mbps = models.PositiveIntegerField(null=True, blank=True)
    poe_padrao = models.CharField(max_length=30, blank=True)
    poe_ativo = models.BooleanField(null=True, blank=True)
    poe_estado = models.CharField(max_length=30, blank=True)

    class Meta:
        verbose_name = "estado de porta"
        verbose_name_plural = "estados de portas"
        constraints = [
            models.UniqueConstraint(fields=["console", "device_id", "coletado_em", "idx"], name="porta_estado_unica")
        ]


# Clientes conectados, consumo e aplicativos (APIs internas do Network) ------------------

class ClienteAmostra(DoConsole):
    """Cada dispositivo conectado, a cada coleta (v2 clients/active). Guardado por 90 dias.
    Não guarda tráfego por aplicativo de cada dispositivo (LGPD)."""

    site = models.CharField(max_length=100)                      # nome interno (ex.: default)
    mac = models.CharField(max_length=50)
    nome = models.CharField(max_length=150, blank=True)
    tipo = models.CharField(max_length=20, blank=True)           # WIRELESS ou WIRED
    fabricante = models.CharField(max_length=150, blank=True)    # pelo prefixo do MAC
    modelo = models.CharField(max_length=150, blank=True)        # identificação do UniFi
    so_id = models.IntegerField(null=True, blank=True)           # traduzido pelo catálogo
    rede = models.CharField(max_length=150, blank=True)
    ssid = models.CharField(max_length=150, blank=True)
    sinal_dbm = models.IntegerField(null=True, blank=True)
    experiencia = models.IntegerField(null=True, blank=True)     # nota Wi-Fi do UniFi (0 a 100)
    retransmissao_pct = models.FloatField(null=True, blank=True)
    porta = models.IntegerField(null=True, blank=True)
    velocidade_mbps = models.IntegerField(null=True, blank=True)
    conectado_seg = models.BigIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "amostra de dispositivo conectado"
        verbose_name_plural = "amostras de dispositivos conectados"
        constraints = [models.UniqueConstraint(fields=["console", "mac", "coletado_em"], name="cliente_amostra_unica")]
        indexes = [models.Index(fields=["cliente", "coletado_em"])]


class InternetDia(DoConsole):
    """Consumo da internet do site por dia (relatório daily.site do console)."""

    site = models.CharField(max_length=100)
    dia = models.DateField()                                      # no horário de Brasília
    download_bytes = models.BigIntegerField(null=True, blank=True)
    upload_bytes = models.BigIntegerField(null=True, blank=True)
    clientes = models.IntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "internet por dia"
        verbose_name_plural = "internet por dia"
        constraints = [models.UniqueConstraint(fields=["console", "site", "dia"], name="internet_dia_unica")]


class InternetHora(DoConsole):
    """Consumo da internet do site por hora (hourly.site), para o horário de pico."""

    site = models.CharField(max_length=100)
    hora = models.DateTimeField()
    download_bytes = models.BigIntegerField(null=True, blank=True)
    upload_bytes = models.BigIntegerField(null=True, blank=True)
    clientes = models.IntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "internet por hora"
        verbose_name_plural = "internet por hora"
        constraints = [models.UniqueConstraint(fields=["console", "site", "hora"], name="internet_hora_unica")]


class ClienteDia(DoConsole):
    """Tráfego de cada dispositivo por dia (daily.user): rede local + internet, sem aplicativos."""

    site = models.CharField(max_length=100)
    mac = models.CharField(max_length=50)
    dia = models.DateField()
    download_bytes = models.BigIntegerField(null=True, blank=True)
    upload_bytes = models.BigIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "dispositivo por dia"
        verbose_name_plural = "dispositivos por dia"
        constraints = [models.UniqueConstraint(fields=["console", "site", "mac", "dia"], name="cliente_dia_unico")]


class AplicativoDia(DoConsole):
    """Tráfego por aplicativo, só no total do site (sem detalhe por pessoa, LGPD)."""

    site = models.CharField(max_length=100)
    dia = models.DateField()
    categoria_id = models.IntegerField()
    aplicativo_id = models.IntegerField()
    download_bytes = models.BigIntegerField(null=True, blank=True)
    upload_bytes = models.BigIntegerField(null=True, blank=True)
    dispositivos = models.IntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "aplicativo por dia"
        verbose_name_plural = "aplicativos por dia"
        constraints = [models.UniqueConstraint(
            fields=["console", "site", "dia", "categoria_id", "aplicativo_id"], name="aplicativo_dia_unico")]


class NaoIdentificadoDia(DoConsole):
    """Tráfego não identificado pelo DPI, somado por família de dispositivo (sem guardar quem é quem)."""

    site = models.CharField(max_length=100)
    dia = models.DateField()
    familia_id = models.IntegerField()                            # -1 = família desconhecida
    bytes = models.BigIntegerField(null=True, blank=True)
    dispositivos = models.IntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "não identificado por dia"
        verbose_name_plural = "não identificado por dia"
        constraints = [models.UniqueConstraint(
            fields=["console", "site", "dia", "familia_id"], name="naoident_dia_unico")]


class ControleColeta(DoConsole):
    """Quando cada coleta "de tempos em tempos" rodou pela última vez em cada site."""

    nome = models.CharField(max_length=50)                       # ex.: consumo
    site = models.CharField(max_length=100)

    class Meta:
        verbose_name = "controle de coleta"
        verbose_name_plural = "controles de coleta"
        constraints = [models.UniqueConstraint(fields=["console", "nome", "site"], name="controle_coleta_unico")]


class Catalogo(models.Model):
    """Tabela de tradução da UniFi (aplicativos, categorias, sistemas...). Igual para todos:
    fica na plataforma, sem organização e sem RLS."""

    tipo = models.CharField(max_length=30)   # dpi_categoria, dpi_aplicativo, so, fabricante, familia, tipo_dispositivo
    id_unifi = models.IntegerField()
    nome = models.CharField(max_length=200, blank=True)
    atualizado_em = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "catálogo"
        verbose_name_plural = "catálogos"
        constraints = [models.UniqueConstraint(fields=["tipo", "id_unifi"], name="catalogo_unico")]
