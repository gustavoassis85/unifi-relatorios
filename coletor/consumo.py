"""Coleta de consumo: internet do site por dia, tráfego de cada cliente por dia e tráfego da rede
por aplicativo por dia.

Fontes (todas do próprio console, pelo connector):
- relatórios diários daily.site e daily.user (leitura, mas a API exige POST);
- tela de tráfego por aplicativo (v2 traffic), só o total do site.

Roda no máximo a cada INTERVALO_HORAS, mesmo com o agendador de hora em hora.
Na primeira vez busca 30 dias; depois, os últimos dias (para completar o dia de hoje).
Sentido validado com a tela do UniFi: nos clientes, tx = download e rx = upload.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from banco.banco import conectar
from coletor.api import ErroApi
from coletor.clientes import sites_do_console
from coletor.equipamentos import CONSOLES_ATIVOS, Ritmo

FUSO = timezone(timedelta(hours=-3))  # Brasília (sem horário de verão desde 2019)
INTERVALO_HORAS = 6
DIAS_PRIMEIRA_VEZ = 30
DIAS_DEPOIS = 3
NAO_IDENTIFICADO = (255, 65535)
BUSCAR_HISTORICO = False  # True (coletar.py --forcar): busca de novo os 30 dias, mesmo com dados no banco  # categoria e aplicativo que o UniFi usa para tráfego não identificado


def _ms(momento):
    return int(momento.timestamp() * 1000)


def _dia(ms):
    return datetime.fromtimestamp(ms / 1000, FUSO).date().isoformat()


def deve_rodar(conexao, chave, intervalo_horas, agora):
    linha = conexao.execute("SELECT ultima FROM controle_coleta WHERE chave = ?", (chave,)).fetchone()
    if not linha:
        return True
    return agora - datetime.fromisoformat(linha["ultima"]) >= timedelta(hours=intervalo_horas)


def marcar(conexao, chave, agora):
    conexao.execute("INSERT OR REPLACE INTO controle_coleta VALUES (?, ?)", (chave, agora.isoformat()))


def _relatorios_diarios(conexao, ritmo, host_id, site, agora, coletado_em):
    primeira = conexao.execute(
        "SELECT COUNT(*) FROM internet_dia WHERE host_id = ? AND site = ?", (host_id, site)
    ).fetchone()[0] == 0
    inicio = agora - timedelta(days=DIAS_PRIMEIRA_VEZ if primeira or BUSCAR_HISTORICO else DIAS_DEPOIS)
    base = f"/v1/connector/consoles/{host_id}/network/api/s/{site}/stat/report"
    periodo = {"start": _ms(inicio), "end": _ms(agora)}

    dias = ritmo.consultar(f"{base}/daily.site",
                           {"attrs": ["time", "wan-rx_bytes", "wan-tx_bytes", "num_sta"], **periodo})
    for d in dias.get("data", []):
        conexao.execute(
            "INSERT OR REPLACE INTO internet_dia VALUES (?, ?, ?, ?, ?, ?, ?)",
            (host_id, site, _dia(d["time"]), d.get("wan-rx_bytes"), d.get("wan-tx_bytes"),
             d.get("num_sta"), coletado_em),
        )

    usuarios = ritmo.consultar(f"{base}/daily.user",
                               {"attrs": ["time", "rx_bytes", "tx_bytes", "user"], **periodo})
    for u in usuarios.get("data", []):
        if u.get("user"):
            conexao.execute(
                "INSERT OR REPLACE INTO cliente_dia VALUES (?, ?, ?, ?, ?, ?, ?)",
                (host_id, site, u["user"], _dia(u["time"]), u.get("tx_bytes"), u.get("rx_bytes"), coletado_em),
            )
    # Por hora (para o horário de pico). Se o console não oferecer, segue sem isso.
    try:
        horas = ritmo.consultar(f"{base}/hourly.site",
                                {"attrs": ["time", "wan-rx_bytes", "wan-tx_bytes", "num_sta"], **periodo})
        for h in horas.get("data", []):
            hora = datetime.fromtimestamp(h["time"] / 1000, FUSO).strftime("%Y-%m-%dT%H")
            conexao.execute(
                "INSERT OR REPLACE INTO internet_hora VALUES (?, ?, ?, ?, ?, ?, ?)",
                (host_id, site, hora, h.get("wan-rx_bytes"), h.get("wan-tx_bytes"), h.get("num_sta"), coletado_em),
            )
    except ErroApi:
        pass
    return len(dias.get("data", [])), len(usuarios.get("data", []))


def _aplicativos(conexao, ritmo, host_id, site, agora, coletado_em):
    tem_dados = conexao.execute(
        "SELECT COUNT(*) FROM aplicativo_dia WHERE host_id = ? AND site = ?", (host_id, site)
    ).fetchone()[0] > 0
    hoje = agora.astimezone(FUSO).replace(hour=0, minute=0, second=0, microsecond=0)
    quantos = DIAS_DEPOIS if tem_dados and not BUSCAR_HISTORICO else DIAS_PRIMEIRA_VEZ
    caminho = f"/v1/connector/consoles/{host_id}/network/v2/api/site/{site}/traffic"
    dias = 0
    for n in range(quantos - 1, -1, -1):
        inicio = hoje - timedelta(days=n)
        fim = min(inicio + timedelta(days=1), agora)
        resposta = ritmo.get(caminho, {"start": _ms(inicio), "end": _ms(fim), "includeUnidentified": "true"})
        # Não identificado por família de dispositivo (soma, sem guardar quem é quem).
        familias = defaultdict(lambda: [0, 0])
        for uso in (resposta or {}).get("client_usage_by_app") or []:
            familia = ((uso.get("client") or {}).get("fingerprint") or {}).get("dev_family")
            nao_ident = sum(a.get("total_bytes") or 0 for a in uso.get("usage_by_app") or []
                            if a.get("application") == NAO_IDENTIFICADO[1])
            if nao_ident:
                familias[familia if familia is not None else -1][0] += nao_ident
                familias[familia if familia is not None else -1][1] += 1
        for familia, (total, dispositivos) in familias.items():
            conexao.execute(
                "INSERT OR REPLACE INTO naoident_familia_dia VALUES (?, ?, ?, ?, ?, ?, ?)",
                (host_id, site, inicio.date().isoformat(), familia, total, dispositivos, coletado_em),
            )
        for app in (resposta or {}).get("total_usage_by_app") or []:
            conexao.execute(
                "INSERT OR REPLACE INTO aplicativo_dia VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (host_id, site, inicio.date().isoformat(), app.get("category"), app.get("application"),
                 app.get("bytes_received"), app.get("bytes_transmitted"), app.get("client_count"), coletado_em),
            )
        dias += 1
    return dias


def coletar():
    agora = datetime.now(timezone.utc)
    coletado_em = agora.isoformat(timespec="seconds")
    conexao = conectar()
    resumo, falhas, pulados = [], [], 0
    try:
        consoles = conexao.execute(CONSOLES_ATIVOS).fetchall()
        if not consoles:
            raise ErroApi("Nenhum console conectado no banco. A coleta de consoles rodou antes?")
        for console in consoles:
            host_id = console["host_id"]
            for site in sites_do_console(conexao, host_id):
                chave = f"consumo:{host_id}:{site}"
                if not deve_rodar(conexao, chave, INTERVALO_HORAS, agora):
                    pulados += 1
                    continue
                ritmo = Ritmo()
                try:
                    with conexao:
                        n_dias, n_usuarios = _relatorios_diarios(conexao, ritmo, host_id, site, agora, coletado_em)
                        n_apps = _aplicativos(conexao, ritmo, host_id, site, agora, coletado_em)
                        marcar(conexao, chave, agora)
                    resumo.append(f"{console['nome']}/{site}: {n_dias} dia(s) de internet, "
                                  f"{n_usuarios} registro(s) de clientes, {n_apps} dia(s) de aplicativos")
                except ErroApi as erro:
                    falhas.append(f"{console['nome']}/{site} ({erro})")
    finally:
        conexao.close()

    if falhas and not resumo and not pulados:
        raise ErroApi("; ".join(falhas))
    if not resumo and not falhas:
        return f"nada a fazer agora (roda a cada {INTERVALO_HORAS}h)"
    texto = "; ".join(resumo) if resumo else "sem novidades"
    if falhas:
        texto += "; falhas: " + "; ".join(falhas)
    return texto
