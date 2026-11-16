"""Coleta das métricas do link (WAN) pela Site Manager: /v1/isp-metrics/1h.

A API guarda as métricas de hora em hora por pelo menos 30 dias.
- Na primeira coleta (banco vazio) buscamos 30 dias de histórico.
- Depois, buscamos os últimos 7 dias. Horários repetidos são atualizados,
  então rodar várias vezes não duplica nada e uma coleta perdida se recupera na próxima.
"""
from datetime import datetime, timezone

from banco.banco import conectar
from coletor.api import get

GRAVAR = """
INSERT INTO wan_hora (
    host_id, site_id, horario, latencia_media, latencia_max, perda_pct,
    uptime_pct, downtime, download_kbps, upload_kbps, provedor, asn, coletado_em
) VALUES (
    :host_id, :site_id, :horario, :latencia_media, :latencia_max, :perda_pct,
    :uptime_pct, :downtime, :download_kbps, :upload_kbps, :provedor, :asn, :coletado_em
)
ON CONFLICT (host_id, site_id, horario) DO UPDATE SET
    latencia_media = excluded.latencia_media,
    latencia_max   = excluded.latencia_max,
    perda_pct      = excluded.perda_pct,
    uptime_pct     = excluded.uptime_pct,
    downtime       = excluded.downtime,
    download_kbps  = excluded.download_kbps,
    upload_kbps    = excluded.upload_kbps,
    provedor       = excluded.provedor,
    asn            = excluded.asn,
    coletado_em    = excluded.coletado_em
"""


def _linhas_da_resposta(resposta, coletado_em):
    """Transforma o JSON da API em linhas prontas para o banco."""
    linhas = []
    for site in resposta.get("data", []):
        for periodo in site.get("periods", []):
            wan = (periodo.get("data") or {}).get("wan") or {}
            linha = {
                "host_id": site.get("hostId"),
                "site_id": site.get("siteId"),
                "horario": periodo.get("metricTime"),
                "latencia_media": wan.get("avgLatency"),
                "latencia_max": wan.get("maxLatency"),
                "perda_pct": wan.get("packetLoss"),
                "uptime_pct": wan.get("uptime"),
                "downtime": wan.get("downtime"),
                "download_kbps": wan.get("download_kbps"),
                "upload_kbps": wan.get("upload_kbps"),
                "provedor": wan.get("ispName"),
                "asn": wan.get("ispAsn"),
                "coletado_em": coletado_em,
            }
            if linha["host_id"] and linha["site_id"] and linha["horario"]:
                linhas.append(linha)
    return linhas


def coletar():
    """Busca as métricas de WAN, grava no banco e devolve um resumo em texto."""
    conexao = conectar()
    try:
        banco_vazio = conexao.execute("SELECT COUNT(*) FROM wan_hora").fetchone()[0] == 0
        duracao = "30d" if banco_vazio else "7d"

        resposta = get("/v1/isp-metrics/1h", {"duration": duracao})
        agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        linhas = _linhas_da_resposta(resposta, agora)

        with conexao:  # grava tudo de uma vez (ou nada, se der erro no meio)
            conexao.executemany(GRAVAR, linhas)
    finally:
        conexao.close()

    sites = len({(l["host_id"], l["site_id"]) for l in linhas})
    janela = "primeira coleta, 30 dias" if banco_vazio else "últimos 7 dias"
    return f"{len(linhas)} horas gravadas de {sites} site(s) ({janela})"
