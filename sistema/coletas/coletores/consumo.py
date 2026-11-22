"""Consumo: internet do site por dia e por hora, tráfego de cada dispositivo por dia e tráfego
da rede por aplicativo por dia. Portado de coletor/consumo.py.

Fontes (do próprio console, pelo connector): relatórios daily.site, daily.user e hourly.site
(leitura, mas a API exige POST) e a tela de tráfego por aplicativo (v2 traffic), só o total.

- Relatórios de internet: no máximo a cada 6 horas por site; na primeira vez (ou com "forçar") 30 dias.
- Aplicativos: o console só guarda o tráfego por aplicativo do dia corrente (desde a meia-noite;
  dias passados voltam vazios, conferido em 21/11/2026). Por isso é buscado em toda coleta de
  hora em hora, só o dia de hoje: a perda fica limitada ao fim do dia depois da última coleta.
Sentido validado com a tela do UniFi: no site, wan-rx = download; nos dispositivos, tx = download.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone as tz
from zoneinfo import ZoneInfo

from unifi.api import ErroApi

from ..models import AplicativoDia, ClienteDia, ControleColeta, InternetDia, InternetHora, NaoIdentificadoDia
from ..tarefas import parte
from .apoio import inteiro, texto
from .clientes import sites_do_console
from .equipamentos import Ritmo, consoles_para_equipamentos

FUSO = ZoneInfo("America/Sao_Paulo")
INTERVALO = timedelta(hours=6)
DIAS_PRIMEIRA_VEZ = 30
DIAS_DEPOIS = 3
APLICATIVO_NAO_IDENTIFICADO = 65535
NOME_CONTROLE = "consumo"


def _ms(momento):
    return int(momento.timestamp() * 1000)


def _momento(ms):
    n = inteiro(ms)
    return datetime.fromtimestamp(n / 1000, tz.utc) if n is not None else None


def _dia(ms):
    m = _momento(ms)
    return m.astimezone(FUSO).date() if m else None


def _deve_rodar(ctx, console, site):
    if ctx.forcar:
        return True
    with ctx.banco():
        controle = ControleColeta.objects.filter(console=console, nome=NOME_CONTROLE, site=site).first()
    return controle is None or ctx.agora - controle.coletado_em >= INTERVALO


def _gravar(modelo, linhas, unicos, atualizar):
    modelo.objects.bulk_create(linhas, update_conflicts=True, unique_fields=unicos, update_fields=atualizar)


ATTRS_SITE = ["time", "wan-rx_bytes", "wan-tx_bytes", "num_sta"]


def _base_linha(ctx, console, site):
    return {"organizacao_id": ctx.organizacao_id, "cliente": ctx.cliente, "console": console,
            "coletado_em": ctx.agora, "site": site}


def _relatorios(ctx, ritmo, console, site):
    """Internet por dia e por hora e dispositivos por dia (a cada 6 horas)."""
    base_linha = _base_linha(ctx, console, site)
    with ctx.banco():
        primeira = not InternetDia.objects.filter(console=console, site=site).exists()
    longo = primeira or ctx.forcar
    inicio = ctx.agora - timedelta(days=DIAS_PRIMEIRA_VEZ if longo else DIAS_DEPOIS)
    periodo = {"start": _ms(inicio), "end": _ms(ctx.agora)}
    base = f"/v1/connector/consoles/{console.host_id}/network/api/s/{site}/stat/report"

    dias = ritmo.consultar(f"{base}/daily.site", {"attrs": ATTRS_SITE, **periodo})
    internet = [
        InternetDia(**base_linha, dia=_dia(d.get("time")), download_bytes=inteiro(d.get("wan-rx_bytes")),
                    upload_bytes=inteiro(d.get("wan-tx_bytes")), clientes=inteiro(d.get("num_sta")))
        for d in dias.get("data") or [] if _dia(d.get("time"))
    ]

    usuarios = ritmo.consultar(f"{base}/daily.user", {"attrs": ["time", "rx_bytes", "tx_bytes", "user"], **periodo})
    por_dispositivo = [
        ClienteDia(**base_linha, mac=texto(u.get("user"), 50), dia=_dia(u.get("time")),
                   download_bytes=inteiro(u.get("tx_bytes")), upload_bytes=inteiro(u.get("rx_bytes")))
        for u in usuarios.get("data") or [] if u.get("user") and _dia(u.get("time"))
    ]

    por_hora = []
    try:  # se o console não oferecer o relatório por hora, segue sem o horário de pico
        horas = ritmo.consultar(f"{base}/hourly.site", {"attrs": ATTRS_SITE, **periodo})
        por_hora = [
            InternetHora(**base_linha, hora=_momento(h.get("time")), download_bytes=inteiro(h.get("wan-rx_bytes")),
                         upload_bytes=inteiro(h.get("wan-tx_bytes")), clientes=inteiro(h.get("num_sta")))
            for h in horas.get("data") or [] if _momento(h.get("time"))
        ]
    except ErroApi:
        pass

    with ctx.banco():
        _gravar(InternetDia, internet, ["console", "site", "dia"],
                ["download_bytes", "upload_bytes", "clientes", "coletado_em"])
        _gravar(ClienteDia, por_dispositivo, ["console", "site", "mac", "dia"],
                ["download_bytes", "upload_bytes", "coletado_em"])
        _gravar(InternetHora, por_hora, ["console", "site", "hora"],
                ["download_bytes", "upload_bytes", "clientes", "coletado_em"])
        ControleColeta.objects.update_or_create(
            organizacao_id=ctx.organizacao_id, cliente=ctx.cliente, console=console, nome=NOME_CONTROLE, site=site,
            defaults={"coletado_em": ctx.agora},
        )
    return len(internet), len(por_dispositivo)


def _aplicativos(ctx, ritmo, console, site):
    """Tráfego por aplicativo de hoje (o console não guarda dias passados). Toda coleta."""
    base_linha = _base_linha(ctx, console, site)
    inicio = ctx.agora.astimezone(FUSO).replace(hour=0, minute=0, second=0, microsecond=0)
    caminho = f"/v1/connector/consoles/{console.host_id}/network/v2/api/site/{site}/traffic"
    aplicativos, nao_identificado = [], []
    resposta = ritmo.get(caminho, {"start": _ms(inicio), "end": _ms(ctx.agora), "includeUnidentified": "true"}) or {}
    dia = inicio.date()
    # Não identificado por família: soma sem guardar qual dispositivo (LGPD).
    familias = defaultdict(lambda: [0, 0])
    for uso in resposta.get("client_usage_by_app") or []:
        familia = inteiro(((uso.get("client") or {}).get("fingerprint") or {}).get("dev_family"))
        bytes_ = sum(inteiro(a.get("total_bytes")) or 0 for a in uso.get("usage_by_app") or []
                     if inteiro(a.get("application")) == APLICATIVO_NAO_IDENTIFICADO)
        if bytes_:
            grupo = familia if familia is not None else -1
            familias[grupo][0] += bytes_
            familias[grupo][1] += 1
    nao_identificado += [NaoIdentificadoDia(**base_linha, dia=dia, familia_id=f, bytes=b, dispositivos=q)
                         for f, (b, q) in familias.items()]
    for app in resposta.get("total_usage_by_app") or []:
        categoria, aplicativo = inteiro(app.get("category")), inteiro(app.get("application"))
        if categoria is None or aplicativo is None:
            continue
        aplicativos.append(AplicativoDia(
            **base_linha, dia=dia, categoria_id=categoria, aplicativo_id=aplicativo,
            download_bytes=inteiro(app.get("bytes_received")), upload_bytes=inteiro(app.get("bytes_transmitted")),
            dispositivos=inteiro(app.get("client_count")),
        ))
    with ctx.banco():
        _gravar(AplicativoDia, aplicativos, ["console", "site", "dia", "categoria_id", "aplicativo_id"],
                ["download_bytes", "upload_bytes", "dispositivos", "coletado_em"])
        _gravar(NaoIdentificadoDia, nao_identificado, ["console", "site", "dia", "familia_id"],
                ["bytes", "dispositivos", "coletado_em"])
    return len(aplicativos)


@parte("Consumo e aplicativos", ordem=50)
def coletar(ctx):
    consoles = consoles_para_equipamentos(ctx)
    if not consoles:
        return "nenhum console conectado"
    resumo, falhas, erros = [], [], []
    for console in consoles:
        for site in sites_do_console(ctx, console):
            ritmo = Ritmo(ctx.api)
            partes_site = []
            try:
                if _deve_rodar(ctx, console, site):
                    n_dias, n_disp = _relatorios(ctx, ritmo, console, site)
                    partes_site.append(f"{n_dias} dia(s) de internet, {n_disp} registro(s) de dispositivos")
                partes_site.append(f"{_aplicativos(ctx, ritmo, console, site)} aplicativo(s) hoje")
            except ErroApi as erro:
                falhas.append(f"{console}/{site} ({erro.mensagem})")
                erros.append(erro)
                if not partes_site:
                    continue
            resumo.append(f"{console}/{site}: " + ", ".join(partes_site))
    if falhas and not resumo:
        raise ErroApi(erros[0].codigo, "; ".join(falhas))
    resultado = "; ".join(resumo)
    if falhas:
        resultado += "; falhas: " + "; ".join(falhas)
    return resultado
