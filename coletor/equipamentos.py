"""Coleta dos equipamentos de cada console pelo connector (API Network via nuvem).

Para cada console conectado:
- lista os sites e grava a quantidade de clientes conectados (cabo e Wi-Fi);
- grava uma foto de cada equipamento: estado, firmware, CPU, memória, uptime, uplink e
  retransmissão dos rádios;
- grava também o detalhe de cada equipamento: portas (velocidade negociada, PoE) e rádios
  (padrão, canal, largura). É coletado em toda execução porque uma foto só engana: um PC em
  repouso negocia 10/100 Mbps, e a regra de "porta abaixo da capacidade" precisa de várias amostras.

Ritmo: a API aceita 100 chamadas por minuto por console. Fazemos no máximo ~85.
Se um console ou equipamento falhar, os outros continuam.
"""
import time
from datetime import datetime, timezone

from banco.banco import conectar
from coletor.api import ErroApi, consultar_relatorio, get

INTERVALO_ENTRE_CHAMADAS = 0.7  # segundos entre chamadas ao mesmo console (~85 por minuto)
TAMANHO_PAGINA = 100

CONSOLES_ATIVOS = """
SELECT host_id, nome FROM console_estado c
WHERE coletado_em = (SELECT MAX(coletado_em) FROM console_estado WHERE host_id = c.host_id)
  AND conectado = 1 AND tipo = 'console'
ORDER BY nome
"""


class Ritmo:
    """Garante um intervalo mínimo entre chamadas ao mesmo console."""

    def __init__(self, intervalo=INTERVALO_ENTRE_CHAMADAS):
        self.intervalo = intervalo
        self.ultima = 0.0
        self.chamadas = 0

    def _chamar(self, funcao, *args):
        espera = self.ultima + self.intervalo - time.monotonic()
        if espera > 0:
            time.sleep(espera)
        try:
            self.chamadas += 1
            return funcao(*args)
        finally:
            self.ultima = time.monotonic()

    def get(self, caminho, parametros=None):
        return self._chamar(get, caminho, parametros)

    def consultar(self, caminho, corpo):
        """Consulta de leitura por POST (só os relatórios de consumo permitidos em coletor/api.py)."""
        return self._chamar(consultar_relatorio, caminho, corpo)


def _todos(ritmo, caminho):
    """Busca todas as páginas de uma lista da API Network (offset/limit)."""
    itens, offset = [], 0
    while True:
        resposta = ritmo.get(caminho, {"offset": offset, "limit": TAMANHO_PAGINA})
        dados = resposta.get("data", [])
        itens.extend(dados)
        offset += len(dados)
        if not dados or offset >= resposta.get("totalCount", 0):
            return itens


def _gravar_detalhe(conexao, device_id, detalhe, agora):
    """Grava portas, rádios e dados de configuração do equipamento."""
    conexao.execute(
        "INSERT OR REPLACE INTO equipamento_detalhe VALUES (?, ?, ?, ?)",
        (device_id, agora, detalhe.get("configurationId"), detalhe.get("provisionedAt")),
    )
    interfaces = detalhe.get("interfaces") or {}
    for porta in interfaces.get("ports") or []:
        poe = porta.get("poe") or {}
        conexao.execute(
            "INSERT OR REPLACE INTO porta_estado VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                device_id, agora, porta.get("idx"), porta.get("state"), porta.get("connector"),
                porta.get("speedMbps"), porta.get("maxSpeedMbps"), poe.get("standard"),
                None if not poe else int(bool(poe.get("enabled"))), poe.get("state"),
            ),
        )
    for posicao, radio in enumerate(interfaces.get("radios") or []):
        conexao.execute(
            "INSERT OR REPLACE INTO radio_config VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                device_id, agora, posicao, radio.get("frequencyGHz"), radio.get("wlanStandard"),
                radio.get("channelWidthMHz"), radio.get("channel"),
            ),
        )


def _coletar_equipamento(conexao, ritmo, base, host_id, site_id, equipamento, agora):
    """Grava a foto de um equipamento. Devolve quantas chamadas dele falharam."""
    device_id = equipamento.get("id")
    caminho = f"{base}/sites/{site_id}/devices/{device_id}"
    falhas = 0

    estatisticas = {}
    if equipamento.get("state") == "ONLINE":
        try:
            estatisticas = ritmo.get(f"{caminho}/statistics/latest")
        except ErroApi:
            falhas += 1

    uplink = estatisticas.get("uplink") or {}
    conexao.execute(
        "INSERT OR REPLACE INTO equipamento_amostra VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            host_id, site_id, device_id, agora, equipamento.get("name"), equipamento.get("model"),
            equipamento.get("macAddress"), equipamento.get("ipAddress"), equipamento.get("state"),
            equipamento.get("firmwareVersion"),
            None if equipamento.get("firmwareUpdatable") is None
            else int(bool(equipamento.get("firmwareUpdatable"))),
            estatisticas.get("uptimeSec"), estatisticas.get("cpuUtilizationPct"),
            estatisticas.get("memoryUtilizationPct"), estatisticas.get("loadAverage1Min"),
            uplink.get("txRateBps"), uplink.get("rxRateBps"),
        ),
    )
    radios = (estatisticas.get("interfaces") or {}).get("radios") or []
    for posicao, radio in enumerate(radios):
        conexao.execute(
            "INSERT OR REPLACE INTO radio_amostra VALUES (?, ?, ?, ?, ?)",
            (device_id, agora, posicao, radio.get("frequencyGHz"), radio.get("txRetriesPct")),
        )

    try:
        _gravar_detalhe(conexao, device_id, ritmo.get(caminho), agora)
    except ErroApi:
        falhas += 1
    return falhas


def _coletar_console(conexao, host_id, agora):
    """Coleta sites, clientes e equipamentos de um console."""
    ritmo = Ritmo()
    base = f"/v1/connector/consoles/{host_id}/network/integration/v1"
    resultado = {"sites": 0, "equipamentos": 0, "clientes": 0, "falhas": 0}

    for site in _todos(ritmo, f"{base}/sites"):
        site_id = site.get("id")
        conexao.execute(
            "INSERT OR REPLACE INTO site_network VALUES (?, ?, ?, ?, ?)",
            (host_id, site_id, site.get("name"), site.get("internalReference"), agora),
        )
        resultado["sites"] += 1

        clientes = _todos(ritmo, f"{base}/sites/{site_id}/clients")
        cabo = sum(1 for c in clientes if c.get("type") == "WIRED")
        wifi = sum(1 for c in clientes if c.get("type") == "WIRELESS")
        conexao.execute(
            "INSERT OR REPLACE INTO clientes_amostra VALUES (?, ?, ?, ?, ?, ?)",
            (host_id, site_id, agora, len(clientes), cabo, wifi),
        )
        resultado["clientes"] += len(clientes)

        for equipamento in _todos(ritmo, f"{base}/sites/{site_id}/devices"):
            resultado["falhas"] += _coletar_equipamento(
                conexao, ritmo, base, host_id, site_id, equipamento, agora
            )
            resultado["equipamentos"] += 1

    resultado["chamadas"] = ritmo.chamadas
    return resultado


def coletar():
    """Coleta todos os consoles conectados e devolve um resumo em texto."""
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")

    conexao = conectar()
    try:
        consoles = conexao.execute(CONSOLES_ATIVOS).fetchall()
        if not consoles:
            raise ErroApi("Nenhum console conectado no banco. A coleta de consoles rodou antes?")

        total = {"sites": 0, "equipamentos": 0, "clientes": 0, "falhas": 0, "chamadas": 0}
        consoles_com_falha = []
        for console in consoles:
            try:
                with conexao:  # grava o console inteiro de uma vez (ou nada, se ele falhar)
                    resultado = _coletar_console(conexao, console["host_id"], agora)
                for chave in total:
                    total[chave] += resultado[chave]
            except ErroApi as erro:
                consoles_com_falha.append(f"{console['nome']} ({erro})")
    finally:
        conexao.close()

    if consoles_com_falha and len(consoles_com_falha) == len(consoles):
        raise ErroApi("nenhum console respondeu: " + "; ".join(consoles_com_falha))

    texto = (
        f"{len(consoles) - len(consoles_com_falha)} console(s), {total['sites']} site(s), "
        f"{total['equipamentos']} equipamento(s), {total['clientes']} cliente(s) conectado(s), "
        f"{total['chamadas']} chamada(s)"
    )
    if total["falhas"]:
        texto += f"; {total['falhas']} chamada(s) de equipamento falharam"
    if consoles_com_falha:
        texto += "; sem resposta: " + "; ".join(consoles_com_falha)
    return texto
