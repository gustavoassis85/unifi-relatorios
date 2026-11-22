"""Métricas do link (WAN) pela Site Manager: /v1/isp-metrics/1h (portado de coletor/wan.py).

Primeira coleta do cliente: 30 dias de histórico. Depois, os últimos 7 dias. Horários
repetidos são atualizados: rodar de novo não duplica e uma coleta perdida se recupera.
Hora que a API não mandou não ganha linha (nunca vira 100% de disponibilidade).
"""
from ..models import WanHora
from ..tarefas import parte
from .apoio import data, inteiro, numero, texto

ATUALIZAR = [
    "latencia_media", "latencia_max", "perda_pct", "uptime_pct", "downtime",
    "download_kbps", "upload_kbps", "provedor", "asn", "coletado_em",
]


@parte("WAN", ordem=20)
def coletar(ctx):
    acompanhados = {c.host_id: c for c in ctx.consoles}
    with ctx.banco():
        primeira = not WanHora.objects.filter(cliente=ctx.cliente).exists()
    resposta = ctx.api.get("/v1/isp-metrics/1h", {"duration": "30d" if primeira else "7d"})

    linhas = []
    for site in (resposta or {}).get("data") or []:
        console = acompanhados.get(site.get("hostId")) if isinstance(site, dict) else None
        if console is None or not site.get("siteId"):
            continue  # console de outro cliente na mesma conta, ou não acompanhado
        for periodo in site.get("periods") or []:
            horario = data(periodo.get("metricTime"))
            if horario is None:
                continue
            wan = (periodo.get("data") or {}).get("wan") or {}
            linhas.append(WanHora(
                organizacao_id=ctx.organizacao_id, cliente=ctx.cliente, console=console,
                coletado_em=ctx.agora, site_id=texto(site.get("siteId"), 100), horario=horario,
                latencia_media=numero(wan.get("avgLatency")), latencia_max=numero(wan.get("maxLatency")),
                perda_pct=numero(wan.get("packetLoss")), uptime_pct=numero(wan.get("uptime")),
                downtime=numero(wan.get("downtime")),
                download_kbps=inteiro(wan.get("download_kbps")), upload_kbps=inteiro(wan.get("upload_kbps")),
                provedor=texto(wan.get("ispName"), 150), asn=texto(wan.get("ispAsn"), 50),
            ))

    with ctx.banco():
        WanHora.objects.bulk_create(
            linhas, update_conflicts=True,
            unique_fields=["console", "site_id", "horario"], update_fields=ATUALIZAR,
        )
    sites = len({(l.console_id, l.site_id) for l in linhas})
    janela = "primeira coleta, 30 dias" if primeira else "últimos 7 dias"
    return f"{len(linhas)} hora(s) de {sites} site(s) ({janela})"
