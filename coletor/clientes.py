"""Coleta dos clientes conectados (API interna v2 do Network, pelo connector).

Por cliente: nome, Wi-Fi ou cabo, fabricante, tipo de dispositivo, código do sistema operacional,
rede, SSID, sinal, nota de experiência Wi-Fi, porta e velocidade do cabo.
Não coleta tráfego por aplicativo de cada pessoa (LGPD): isso fica só no total do site.
"""
from datetime import datetime, timezone

from banco.banco import conectar
from coletor.api import ErroApi
from coletor.equipamentos import CONSOLES_ATIVOS, Ritmo

GRAVAR = """
INSERT OR REPLACE INTO cliente_amostra (
    host_id, site, coletado_em, mac, nome, tipo, fabricante, modelo, so_id, rede, ssid,
    sinal_dbm, experiencia, retransmissao_pct, porta, velocidade_mbps, conectado_seg
) VALUES (
    :host_id, :site, :coletado_em, :mac, :nome, :tipo, :fabricante, :modelo, :so_id, :rede, :ssid,
    :sinal_dbm, :experiencia, :retransmissao_pct, :porta, :velocidade_mbps, :conectado_seg
)
"""


def sites_do_console(conexao, host_id):
    """Nomes internos dos sites do console (ex.: default), vistos pela coleta de equipamentos."""
    linhas = conexao.execute(
        "SELECT DISTINCT referencia FROM site_network WHERE host_id = ? AND referencia IS NOT NULL",
        (host_id,),
    ).fetchall()
    return [l["referencia"] for l in linhas] or ["default"]


def _linha(cliente, host_id, site, agora):
    tipo = cliente.get("type") or ("WIRED" if cliente.get("is_wired") else "WIRELESS")
    return {
        "host_id": host_id, "site": site, "coletado_em": agora,
        "mac": cliente.get("mac") or cliente.get("id"),
        "nome": cliente.get("display_name") or cliente.get("hostname") or cliente.get("name"),
        "tipo": tipo,
        "fabricante": cliente.get("oui"),
        "modelo": cliente.get("model_name"),
        "so_id": (cliente.get("fingerprint") or {}).get("os_name"),
        "rede": cliente.get("network_name"),
        "ssid": cliente.get("essid"),
        "sinal_dbm": cliente.get("signal") if tipo == "WIRELESS" else None,
        "experiencia": cliente.get("wifi_experience_score") if tipo == "WIRELESS" else None,
        "retransmissao_pct": cliente.get("wifi_tx_retries_percentage") if tipo == "WIRELESS" else None,
        "porta": cliente.get("sw_port"),
        "velocidade_mbps": cliente.get("wired_rate_mbps"),
        "conectado_seg": cliente.get("uptime"),
    }


def coletar():
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conexao = conectar()
    total, falhas = 0, []
    try:
        consoles = conexao.execute(CONSOLES_ATIVOS).fetchall()
        if not consoles:
            raise ErroApi("Nenhum console conectado no banco. A coleta de consoles rodou antes?")
        for console in consoles:
            ritmo = Ritmo()
            base = f"/v1/connector/consoles/{console['host_id']}/network/v2/api/site"
            try:
                with conexao:
                    for site in sites_do_console(conexao, console["host_id"]):
                        resposta = ritmo.get(f"{base}/{site}/clients/active")
                        for cliente in resposta if isinstance(resposta, list) else []:
                            linha = _linha(cliente, console["host_id"], site, agora)
                            if linha["mac"]:
                                conexao.execute(GRAVAR, linha)
                                total += 1
            except ErroApi as erro:
                falhas.append(f"{console['nome']} ({erro})")
    finally:
        conexao.close()

    if falhas and len(falhas) == len(consoles):
        raise ErroApi("nenhum console respondeu: " + "; ".join(falhas))
    texto = f"{total} cliente(s) conectado(s) gravado(s)"
    if falhas:
        texto += "; sem resposta: " + "; ".join(falhas)
    return texto
