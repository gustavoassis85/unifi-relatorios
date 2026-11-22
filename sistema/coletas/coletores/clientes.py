"""Dispositivos conectados (API interna v2 do Network, pelo connector). Portado de coletor/clientes.py.

Por dispositivo: nome, Wi-Fi ou cabo, fabricante, tipo, código do sistema, rede, SSID, sinal,
nota de experiência Wi-Fi, porta e velocidade do cabo. Não coleta tráfego por aplicativo
de cada pessoa (LGPD): isso fica só no total do site.
"""
from unifi.api import ErroApi

from ..models import ClienteAmostra, SiteNetwork
from ..tarefas import parte
from .apoio import inteiro, numero, texto
from .equipamentos import Ritmo, consoles_para_equipamentos


def sites_do_console(ctx, console):
    """Nomes internos dos sites (ex.: default), vistos pela coleta de equipamentos."""
    with ctx.banco():
        nomes = SiteNetwork.objects.filter(console=console).exclude(referencia="").values_list("referencia", flat=True)
        return sorted(set(nomes)) or ["default"]


def _amostra(ctx, console, site, d):
    tipo = d.get("type") or ("WIRED" if d.get("is_wired") else "WIRELESS")
    wifi = tipo == "WIRELESS"
    return ClienteAmostra(
        organizacao_id=ctx.organizacao_id, cliente=ctx.cliente, console=console, coletado_em=ctx.agora,
        site=site, mac=texto(d.get("mac") or d.get("id"), 50),
        nome=texto(d.get("display_name") or d.get("hostname") or d.get("name"), 150),
        tipo=texto(tipo, 20), fabricante=texto(d.get("oui"), 150), modelo=texto(d.get("model_name"), 150),
        so_id=inteiro((d.get("fingerprint") or {}).get("os_name")), rede=texto(d.get("network_name"), 150),
        ssid=texto(d.get("essid"), 150),
        sinal_dbm=inteiro(d.get("signal")) if wifi else None,
        experiencia=inteiro(d.get("wifi_experience_score")) if wifi else None,
        retransmissao_pct=numero(d.get("wifi_tx_retries_percentage")) if wifi else None,
        porta=inteiro(d.get("sw_port")), velocidade_mbps=inteiro(d.get("wired_rate_mbps")),
        conectado_seg=inteiro(d.get("uptime")),
    )


@parte("Dispositivos conectados", ordem=40)
def coletar(ctx):
    consoles = consoles_para_equipamentos(ctx)
    if not consoles:
        return "nenhum console conectado"
    total, falhas, erros = 0, [], []
    for console in consoles:
        ritmo = Ritmo(ctx.api)
        base = f"/v1/connector/consoles/{console.host_id}/network/v2/api/site"
        try:
            linhas = []
            for site in sites_do_console(ctx, console):
                resposta = ritmo.get(f"{base}/{site}/clients/active")
                for d in resposta if isinstance(resposta, list) else []:
                    if isinstance(d, dict) and (d.get("mac") or d.get("id")):
                        linhas.append(_amostra(ctx, console, site, d))
            with ctx.banco():
                ClienteAmostra.objects.bulk_create(linhas, ignore_conflicts=True)
            total += len(linhas)
        except ErroApi as erro:
            falhas.append(f"{console} ({erro.mensagem})")
            erros.append(erro)
    if len(falhas) == len(consoles):
        raise ErroApi(erros[0].codigo, "Nenhum console respondeu: " + "; ".join(falhas))
    resumo = f"{total} dispositivo(s) conectado(s)"
    if falhas:
        resumo += "; sem resposta: " + "; ".join(falhas)
    return resumo
