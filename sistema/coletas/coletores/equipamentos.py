"""Equipamentos de cada console pelo connector (portado de coletor/equipamentos.py).

Para cada console acompanhado e conectado:
- sites e quantidade de clientes conectados (cabo e Wi-Fi);
- foto de cada equipamento: estado, firmware, CPU, memória, uptime, uplink, retransmissão dos rádios;
- detalhe em toda coleta: portas (velocidade negociada, PoE) e rádios (padrão, canal, largura).

Ritmo: a API aceita 100 chamadas por minuto por console; fazemos no máximo ~85.
Cada console é gravado inteiro ou não é gravado. Se um console ou equipamento falha, os outros seguem.
"""
import time

from unifi.api import ErroApi

from ..models import (
    ClientesAmostra, EquipamentoAmostra, PortaEstado, RadioAmostra, RadioConfig, SiteNetwork,
)
from ..tarefas import parte
from .apoio import data, inteiro, numero, texto

INTERVALO_ENTRE_CHAMADAS = 0.7  # segundos entre chamadas ao mesmo console (~85 por minuto)
TAMANHO_PAGINA = 100
MAX_PAGINAS = 50


class Ritmo:
    """Garante um intervalo mínimo entre chamadas ao mesmo console."""

    def __init__(self, api, intervalo=INTERVALO_ENTRE_CHAMADAS):
        self.api = api
        self.intervalo = intervalo
        self.ultima = None
        self.chamadas = 0

    def _esperar(self):
        if self.ultima is not None:
            espera = self.ultima + self.intervalo - time.monotonic()
            if espera > 0:
                time.sleep(espera)

    def get(self, caminho, parametros=None):
        self._esperar()
        try:
            self.chamadas += 1
            return self.api.get(caminho, parametros) or {}
        finally:
            self.ultima = time.monotonic()

    def consultar(self, caminho, corpo):
        """Consulta de leitura por POST (só os relatórios permitidos em unifi/api.py)."""
        self._esperar()
        try:
            self.chamadas += 1
            return self.api.consultar_relatorio(caminho, corpo) or {}
        finally:
            self.ultima = time.monotonic()


def todos(ritmo, caminho):
    """Todas as páginas de uma lista da API Network (offset/limit)."""
    itens, offset = [], 0
    for _ in range(MAX_PAGINAS):
        resposta = ritmo.get(caminho, {"offset": offset, "limit": TAMANHO_PAGINA})
        dados = [d for d in resposta.get("data") or [] if isinstance(d, dict)]
        itens.extend(dados)
        offset += len(dados)
        if not dados or offset >= (inteiro(resposta.get("totalCount")) or 0):
            break
    return itens


def _bool(valor):
    return None if valor is None else bool(valor)


class Gravacao:
    """Junta as linhas de um console para gravar tudo de uma vez."""

    def __init__(self, ctx, console):
        self.base = {"organizacao_id": ctx.organizacao_id, "cliente": ctx.cliente, "console": console,
                     "coletado_em": ctx.agora}
        self.linhas = {m: [] for m in (SiteNetwork, ClientesAmostra, EquipamentoAmostra,
                                       RadioAmostra, RadioConfig, PortaEstado)}

    def add(self, tabela, /, **campos):
        self.linhas[tabela].append(tabela(**self.base, **campos))

    def gravar(self):
        for modelo, linhas in self.linhas.items():
            if modelo is SiteNetwork:
                modelo.objects.bulk_create(
                    linhas, update_conflicts=True, unique_fields=["console", "site_id"],
                    update_fields=["nome", "referencia", "coletado_em"],
                )
            else:
                modelo.objects.bulk_create(linhas, ignore_conflicts=True)

    def conta(self, modelo):
        return len(self.linhas[modelo])


def _equipamento(g, ritmo, base, site_id, equip):
    """Foto e detalhe de um equipamento. Devolve quantas chamadas dele falharam."""
    device_id = texto(equip.get("id"), 100)
    caminho = f"{base}/sites/{site_id}/devices/{device_id}"
    falhas = 0

    estatisticas = {}
    if equip.get("state") == "ONLINE":
        try:
            estatisticas = ritmo.get(f"{caminho}/statistics/latest")
        except ErroApi:
            falhas += 1
    detalhe = {}
    try:
        detalhe = ritmo.get(caminho)
    except ErroApi:
        falhas += 1

    uplink = estatisticas.get("uplink") or {}
    g.add(
        EquipamentoAmostra, site_id=site_id, device_id=device_id,
        nome=texto(equip.get("name"), 150), modelo=texto(equip.get("model"), 100),
        mac=texto(equip.get("macAddress"), 50), ip=texto(equip.get("ipAddress"), 50),
        estado=texto(equip.get("state"), 30), firmware=texto(equip.get("firmwareVersion"), 50),
        firmware_atualizavel=_bool(equip.get("firmwareUpdatable")),
        uptime_seg=inteiro(estatisticas.get("uptimeSec")), cpu_pct=numero(estatisticas.get("cpuUtilizationPct")),
        memoria_pct=numero(estatisticas.get("memoryUtilizationPct")),
        carga_1min=numero(estatisticas.get("loadAverage1Min")),
        uplink_tx_bps=inteiro(uplink.get("txRateBps")), uplink_rx_bps=inteiro(uplink.get("rxRateBps")),
        configuracao_id=texto(detalhe.get("configurationId"), 100),
        provisionado_em=data(detalhe.get("provisionedAt")),
    )
    for posicao, radio in enumerate((estatisticas.get("interfaces") or {}).get("radios") or []):
        g.add(RadioAmostra, device_id=device_id, posicao=posicao,
              frequencia_ghz=numero(radio.get("frequencyGHz")), retransmissao_pct=numero(radio.get("txRetriesPct")))

    interfaces = detalhe.get("interfaces") or {}
    for porta in interfaces.get("ports") or []:
        idx = inteiro(porta.get("idx"))
        if idx is None:
            continue
        poe = porta.get("poe") or {}
        g.add(PortaEstado, device_id=device_id, idx=idx, estado=texto(porta.get("state"), 20),
              conector=texto(porta.get("connector"), 30), velocidade_mbps=inteiro(porta.get("speedMbps")),
              velocidade_max_mbps=inteiro(porta.get("maxSpeedMbps")), poe_padrao=texto(poe.get("standard"), 30),
              poe_ativo=None if not poe else bool(poe.get("enabled")), poe_estado=texto(poe.get("state"), 30))
    for posicao, radio in enumerate(interfaces.get("radios") or []):
        g.add(RadioConfig, device_id=device_id, posicao=posicao, frequencia_ghz=numero(radio.get("frequencyGHz")),
              padrao=texto(radio.get("wlanStandard"), 30), largura_mhz=inteiro(radio.get("channelWidthMHz")),
              canal=inteiro(radio.get("channel")))
    return falhas


def coletar_console(ctx, console):
    ritmo = Ritmo(ctx.api)
    base = f"/v1/connector/consoles/{console.host_id}/network/integration/v1"
    g = Gravacao(ctx, console)
    clientes, falhas = 0, 0
    for site in todos(ritmo, f"{base}/sites"):
        site_id = texto(site.get("id"), 100)
        if not site_id:
            continue
        g.add(SiteNetwork, site_id=site_id, nome=texto(site.get("name"), 150),
              referencia=texto(site.get("internalReference"), 100))
        conectados = todos(ritmo, f"{base}/sites/{site_id}/clients")
        g.add(ClientesAmostra, site_id=site_id, total=len(conectados),
              cabo=sum(1 for c in conectados if c.get("type") == "WIRED"),
              wifi=sum(1 for c in conectados if c.get("type") == "WIRELESS"))
        clientes += len(conectados)
        for equip in todos(ritmo, f"{base}/sites/{site_id}/devices"):
            if equip.get("id"):
                falhas += _equipamento(g, ritmo, base, site_id, equip)
    with ctx.banco():
        g.gravar()
    return {"sites": g.conta(SiteNetwork), "equipamentos": g.conta(EquipamentoAmostra),
            "clientes": clientes, "falhas": falhas, "chamadas": ritmo.chamadas}


def consoles_para_equipamentos(ctx):
    """Consoles acompanhados, conectados e com o Network embarcado (não network-server)."""
    conectados = ctx.extras.get("conectados")
    if conectados is None:  # a parte de consoles falhou: usa a última situação conhecida
        conectados = [c for c in ctx.consoles if c.conectado and c.na_conta]
    return [c for c in conectados if c.tipo != "network-server"]


@parte("Equipamentos", ordem=30)
def coletar(ctx):
    consoles = consoles_para_equipamentos(ctx)
    if not consoles:
        return "nenhum console conectado"
    total = {"sites": 0, "equipamentos": 0, "clientes": 0, "falhas": 0, "chamadas": 0}
    sem_resposta, erros = [], []
    for console in consoles:
        try:
            resultado = coletar_console(ctx, console)
        except ErroApi as erro:
            sem_resposta.append(f"{console} ({erro.mensagem})")
            erros.append(erro)
            continue
        for nome in total:
            total[nome] += resultado[nome]
    if len(sem_resposta) == len(consoles):
        raise ErroApi(erros[0].codigo, "Nenhum console respondeu: " + "; ".join(sem_resposta))
    resumo = (
        f"{len(consoles) - len(sem_resposta)} console(s), {total['sites']} site(s), "
        f"{total['equipamentos']} equipamento(s), {total['clientes']} cliente(s) conectado(s), "
        f"{total['chamadas']} chamada(s)"
    )
    if total["falhas"]:
        resumo += f"; {total['falhas']} chamada(s) de equipamento falharam"
    if sem_resposta:
        resumo += "; sem resposta: " + "; ".join(sem_resposta)
    return resumo
