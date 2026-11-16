"""Monta o relatório de saúde da rede de um console (HTML pronto para imprimir em PDF).

Visual inspirado no Site Manager da UniFi, para quem já usa a plataforma se sentir em casa:
fundo escuro, painéis com borda fina, tabelas com bolinha de status e azul só no que é ação.
O tema (escuro ou claro) e a marca do MSP ficam em relatorio/marca.json.
"""
import base64
import json
from collections import defaultdict
from datetime import timedelta
from html import escape
from pathlib import Path
from statistics import mean

from achados.regras import FUSO, LIMITES, _chave, _dt, avaliar
from relatorio import graficos

PASTA = Path(__file__).resolve().parent
SEVERIDADE = {  # rótulo e classe de cor
    "alta": ("Alta", "critico"),
    "media": ("Média", "atencao"),
    "baixa": ("Baixa", "neutro"),
    "info": ("Informativo", "neutro"),
}


def carregar_marca():
    marca = json.loads((PASTA / "marca.json").read_text(encoding="utf-8"))
    marca["logo_html"] = ""
    logo = marca.get("logo")
    if logo and Path(logo).is_file():
        tipo = "svg+xml" if logo.lower().endswith(".svg") else "png"
        dados = base64.b64encode(Path(logo).read_bytes()).decode()
        marca["logo_html"] = f'<img class="logo" src="data:image/{tipo};base64,{dados}" alt="{escape(marca.get("empresa", ""))}">'
    return marca


def _num(valor, casas=1):
    return "-" if valor is None else f"{valor:.{casas}f}".replace(".", ",")


def _situacao(achados):
    if any(a.severidade == "alta" for a in achados):
        return "critico", "Rede com pontos críticos que pedem ação no próximo mês."
    if any(a.severidade == "media" for a in achados):
        return "atencao", "Rede funcionando, com pontos de atenção que merecem acompanhamento."
    return "ok", "Rede saudável no período, sem pontos de atenção relevantes."


def _periodo_sql(conexao, sql, inicio, fim, parametros, coluna="coletado_em"):
    filtro = f" AND substr({coluna}, 1, 19) >= ? AND substr({coluna}, 1, 19) <= ? ORDER BY {coluna}"
    return conexao.execute(sql + filtro, (*parametros, _chave(inicio), _chave(fim))).fetchall()


# ---------------------------------------------------------------- dados

def _estado_dia(dia, completo):
    """Classifica o dia para a faixa de saúde do link."""
    if dia["horas"] == 0:
        return "vazio"
    if dia["horas"] < LIMITES["perda_min_horas_dia"]:
        return "parcial"
    perda, pico = dia["perda"] or 0, dia["pico"] or 0
    sem_dado = 24 - dia["horas"] if completo else 0
    if perda >= LIMITES["perda_dia_alta"] or pico >= LIMITES["perda_hora_alta"] \
            or sem_dado >= LIMITES["wan_sequencia_sem_dado_alta"]:
        return "critico"
    if perda >= LIMITES["perda_dia_instavel"] or pico >= LIMITES["perda_hora_pico"] or sem_dado >= 1:
        return "atencao"
    return "ok"


def _dados_link(conexao, host_id, inicio, fim):
    horas = _periodo_sql(conexao, "SELECT * FROM wan_hora WHERE host_id = ?", inicio, fim, (host_id,), "horario")
    if not horas:
        return None
    momentos = [_dt(h["horario"]) for h in horas]
    esperadas = int((max(momentos) - min(momentos)).total_seconds() // 3600) + 1
    por_dia = defaultdict(list)
    for h, m in zip(horas, momentos):
        por_dia[m.date()].append(h)

    dias, dia, ultimo = [], min(momentos).date(), max(momentos).date()
    while dia <= ultimo:
        hs = por_dia.get(dia, [])
        perdas = [h["perda_pct"] for h in hs if h["perda_pct"] is not None]
        latencias = [h["latencia_media"] for h in hs if h["latencia_media"] is not None]
        dias.append({
            "dia": dia, "rotulo": dia.strftime("%d/%m"), "horas": len(hs),
            "perda": mean(perdas) if perdas else None,
            "pico": max(perdas) if perdas else None,
            "latencia": mean(latencias) if latencias else None,
        })
        dia += timedelta(days=1)
    for i, d in enumerate(dias):
        d["completo"] = 0 < i < len(dias) - 1  # primeiro e último dia são naturalmente incompletos
        d["estado"] = _estado_dia(d, d["completo"])

    perdas = [h["perda_pct"] for h in horas if h["perda_pct"] is not None]
    pior = max(horas, key=lambda h: h["perda_pct"] or 0)
    avaliados = [d for d in dias if d["estado"] in ("ok", "atencao", "critico")]
    return {
        "provedor": next((h["provedor"] for h in horas if h["provedor"]), "Operadora"),
        "plano": next(((h["download_kbps"], h["upload_kbps"]) for h in horas if h["download_kbps"]), None),
        "esperadas": esperadas,
        "presentes": len(horas),
        "disponibilidade": 100 * len(horas) / esperadas,
        "perda_media": mean(perdas) if perdas else None,
        "pior_hora": pior,
        "latencia_media": mean(h["latencia_media"] for h in horas if h["latencia_media"] is not None),
        "dias": dias,
        "dias_estaveis": sum(1 for d in avaliados if d["estado"] == "ok"),
        "dias_avaliados": len(avaliados),
        "marcados": {d["rotulo"] for d in dias if d["completo"] and d["horas"] < 24},
        "parciais": {d["rotulo"] for d in dias if d["estado"] in ("parcial", "vazio")},
    }


def _dados_equipamentos(conexao, host_id, inicio, fim):
    amostras = defaultdict(list)
    for a in _periodo_sql(conexao, "SELECT * FROM equipamento_amostra WHERE host_id = ?", inicio, fim, (host_id,)):
        amostras[a["device_id"]].append(a)
    resultado = []
    for lista in amostras.values():
        ultima = lista[-1]
        cpu = [a["cpu_pct"] for a in lista if a["cpu_pct"] is not None]
        memoria = [a["memoria_pct"] for a in lista if a["memoria_pct"] is not None]
        resultado.append({
            "nome": ultima["nome"], "modelo": ultima["modelo"], "firmware": ultima["firmware"],
            "estado": ultima["estado"], "atualizavel": bool(ultima["firmware_atualizavel"]),
            "online": 100 * sum(1 for a in lista if a["estado"] == "ONLINE") / len(lista),
            "cpu": mean(cpu) if cpu else None,
            "memoria": mean(memoria) if memoria else None,
            "ligado_dias": ultima["uptime_seg"] // 86400 if ultima["uptime_seg"] is not None else None,
        })
    return sorted(resultado, key=lambda e: e["nome"] or "")


def _dados_clientes(conexao, host_id, inicio, fim):
    linhas = _periodo_sql(conexao, "SELECT * FROM clientes_amostra WHERE host_id = ?", inicio, fim, (host_id,))
    if not linhas:
        return None
    pico = max(linhas, key=lambda l: l["total"])
    return {"media": mean(l["total"] for l in linhas), "pico": pico["total"],
            "pico_cabo": pico["cabo"], "pico_wifi": pico["wifi"]}


# ---------------------------------------------------------------- blocos de HTML

def _ponto(classe):
    return f'<span class="ponto {classe}" aria-hidden="true"></span>'


def _kpi(rotulo, valor, detalhe=""):
    return (f'<div class="kpi"><div class="kpi-rotulo">{rotulo}</div><div class="kpi-valor">{valor}</div>'
            + (f'<div class="kpi-detalhe">{detalhe}</div>' if detalhe else "") + "</div>")


def _bloco_site(console):
    if console["conectado"] and console["atualizacao_disponivel"]:
        status = f'<span class="acao">Atualizar para {escape(console["atualizacao_disponivel"].split("+")[0])}</span>'
    else:
        status = "Online" if console["conectado"] else '<span class="apagado">Offline</span>'
    backup = _dt(console["ultimo_backup"]).strftime("%d/%m/%Y") if console["ultimo_backup"] else "Sem registro"
    return (
        '<section class="painel"><table class="tabela tabela-site"><thead><tr>'
        '<th>Nome</th><th>Modelo</th><th>Status</th><th>Versão</th><th>Backup em nuvem</th></tr></thead>'
        f'<tbody><tr><td class="nome">{_ponto("ok" if console["conectado"] else "neutro")}'
        f'{escape(console["nome"] or "Console")}</td><td>{escape(console["modelo"] or "-")}</td>'
        f'<td>{status}</td><td>{escape(console["firmware"] or console["versao_os"] or "-")}</td>'
        f'<td>{backup}</td></tr></tbody></table></section>'
    )


def _bloco_trilho(achados, equipamentos, clientes, detalhe):
    contagem = "".join(
        f'<li>{_ponto(SEVERIDADE[s][1])}<span>{SEVERIDADE[s][0]}</span>'
        f'<span class="qtd">{sum(1 for a in achados if a.severidade == s)}</span></li>'
        for s in ("alta", "media", "baixa", "info")
    )
    rede = []
    if equipamentos:
        online = sum(1 for e in equipamentos if e["estado"] == "ONLINE")
        rede.append(("Equipamentos online", f"{online} de {len(equipamentos)}"))
    if detalhe:
        rede.append(("Clientes no período", str(detalhe["quantidade"])))
    if clientes:
        rede += [("Média de clientes", _num(clientes["media"], 0)),
                 ("Pico de clientes", str(clientes["pico"])),
                 ("Wi-Fi e cabo no pico", f"{clientes['pico_wifi']} e {clientes['pico_cabo']}")]
    linhas_rede = "".join(f'<li><span>{r}</span><span class="qtd">{v}</span></li>' for r, v in rede)
    bloco_rede = (f'<h2 class="separado">Rede</h2><ul class="contagem">{linhas_rede}</ul>' if rede else "")
    return (f'<aside class="painel trilho"><h2>Pontos de atenção</h2><ul class="contagem">{contagem}</ul>'
            f'{bloco_rede}</aside>')


def _bloco_link(link):
    if not link:
        return ('<section class="painel"><div class="painel-topo"><h2>Saúde do link</h2></div>'
                '<p class="vazio-texto">Ainda não há métricas do link neste período.</p></section>')
    plano = f"{link['plano'][0] // 1000}/{link['plano'][1] // 1000} Mbps" if link["plano"] else ""
    legenda = "".join(
        f'<span>{_ponto(classe)}{texto}</span>'
        for classe, texto in (("ok", "Estável"), ("atencao", "Instável"), ("critico", "Crítico"),
                              ("parcial", "Poucos dados"))
    )
    pior = link["pior_hora"]
    kpis = "".join([
        _kpi("Disponibilidade estimada", f"{_num(link['disponibilidade'])}%",
             f"{link['presentes']} de {link['esperadas']} horas com dados"),
        _kpi("Dias estáveis", f"{link['dias_estaveis']} de {link['dias_avaliados']}"),
        _kpi("Perda de pacote média", f"{_num(link['perda_media'])}%",
             f"pior hora: {_num(pior['perda_pct'], 0)}% em {_dt(pior['horario']):%d/%m %Hh}"),
        _kpi("Latência média", f"{_num(link['latencia_media'])} ms"),
    ])
    return (
        '<section class="painel painel-link"><div class="painel-topo"><h2>Saúde do link</h2>'
        f'<span class="meta">{escape(link["provedor"])}{", " + plano if plano else ""}</span></div>'
        + graficos.faixa_dias([d["rotulo"] for d in link["dias"]], [d["estado"] for d in link["dias"]],
                              "Saúde do link por dia")
        + f'<div class="legenda">{legenda}</div><div class="kpis">{kpis}</div></section>'
    )


def _bloco_achados(achados):
    if not achados:
        return ('<section class="painel"><div class="painel-topo"><h2>Pontos de atenção</h2></div>'
                '<p class="vazio-texto">Nenhum ponto de atenção no período.</p></section>')
    linhas = "".join(
        f'<tr><td class="sev">{_ponto(SEVERIDADE[a.severidade][1])}{SEVERIDADE[a.severidade][0]}</td>'
        f'<td><div class="titulo">{escape(a.titulo)}</div><div class="secundario">{escape(a.evidencia)}</div></td>'
        f'<td class="area">{a.area}</td></tr>'
        for a in achados
    )
    return ('<section class="painel painel-quebra"><div class="painel-topo"><h2>Pontos de atenção</h2>'
            f'<span class="meta">{len(achados)} no período</span></div>'
            '<table class="tabela"><thead><tr><th>Gravidade</th><th>Ponto de atenção</th><th>Área</th></tr></thead>'
            f'<tbody>{linhas}</tbody></table></section>')


def _bloco_passos(achados):
    acionaveis = [a for a in achados if a.severidade in ("alta", "media")]
    if not acionaveis:
        return ""
    itens = "".join(
        f'<li><div class="titulo">{escape(a.titulo)}</div><div class="secundario">{escape(a.recomendacao)}</div></li>'
        for a in acionaveis
    )
    return ('<section class="painel painel-quebra"><div class="painel-topo"><h2>Próximos passos</h2>'
            '<span class="meta">em ordem de prioridade</span></div>'
            f'<ol class="passos">{itens}</ol></section>')


def _bloco_graficos(link):
    if not link:
        return ""
    rotulos = [d["rotulo"] for d in link["dias"]]
    nota_legenda = (f"Linha tracejada: limite de {_num(LIMITES['perda_dia_instavel'])}% de perda média no dia. "
                    "Em vermelho, os dias acima do limite.")
    if link["parciais"]:
        nota_legenda += " Em cinza, dias com poucos dados."
    if link["marcados"]:
        nota_legenda += " Triângulo: dia com horas sem nenhum dado do link."
    return (
        '<section class="painel"><div class="painel-topo"><h2>Perda de pacote por dia</h2>'
        '<span class="meta">média diária</span></div>'
        + graficos.barras(rotulos, [d["perda"] for d in link["dias"]], limite=LIMITES["perda_dia_instavel"],
                          marcados=link["marcados"], parciais=link["parciais"], rotulo="Perda de pacote por dia")
        + f'<p class="nota-rodape">{nota_legenda}</p></section>'
        '<section class="painel"><div class="painel-topo"><h2>Latência por dia</h2>'
        '<span class="meta">média diária</span></div>'
        + graficos.linha(rotulos, [d["latencia"] for d in link["dias"]], rotulo="Latência média por dia")
        + "</section>"
    )


def _bloco_dispositivos(equipamentos, clientes):
    if not equipamentos:
        return ""
    linhas = "".join(
        f'<tr><td class="nome">{_ponto("ok" if e["estado"] == "ONLINE" else "neutro")}{escape(e["nome"] or "-")}</td>'
        f'<td>{escape(e["modelo"] or "-")}</td>'
        f'<td>{"<span class=acao>Atualização disponível</span>" if e["atualizavel"] else ("Online" if e["estado"] == "ONLINE" else "<span class=apagado>Offline</span>")}</td>'
        f'<td>{escape(e["firmware"] or "-")}</td><td class="num">{_num(e["online"])}%</td>'
        f'<td class="num">{_num(e["cpu"])}%</td><td class="num">{_num(e["memoria"])}%</td>'
        f'<td class="num">{"-" if e["ligado_dias"] is None else str(e["ligado_dias"]) + " dias"}</td></tr>'
        for e in equipamentos
    )
    rodape = ""
    if clientes:
        rodape = (f'<div class="rodape-painel">Clientes conectados: {_num(clientes["media"], 0)} em média, '
                  f'pico de {clientes["pico"]} ({clientes["pico_cabo"]} cabo, {clientes["pico_wifi"]} Wi-Fi).</div>')
    return ('<section class="painel"><div class="painel-topo"><h2>Equipamentos UniFi</h2>'
            '<span class="meta">CPU e memória: médias do período</span></div>'
            '<table class="tabela tabela-compacta"><thead><tr>'
            '<th>Nome</th><th>Modelo</th><th>Status</th><th>Versão</th><th class="num">Online</th>'
            '<th class="num">CPU</th><th class="num">Memória</th><th class="num">Ligado há</th>'
            f'</tr></thead><tbody>{linhas}</tbody></table>{rodape}</section>')


# ---------------------------------------------------------------- consumo, aplicativos e clientes

NAO_IDENTIFICADO_APP = 65535
NAO_IDENTIFICADO_CAT = 255

# O catálogo do UniFi vem em inglês; as categorias mais comuns ganham nome em português.
CATEGORIAS_PT = {
    "instant messengers": "Mensageiros", "peer-to-peer networks": "Redes P2P",
    "file sharing services and tools": "Compartilhamento de arquivos",
    "media streaming services": "Streaming de vídeo e áudio", "email messaging services": "E-mail",
    "voip services": "Chamadas de voz (VoIP)", "database systems": "Bancos de dados",
    "online games": "Jogos online", "network management tools and protocols": "Gerenciamento de rede",
    "remote access terminals": "Acesso remoto", "bypass proxies and tunnels": "Proxies e túneis",
    "stock market": "Bolsa de valores", "web services": "Serviços web", "security updates": "Atualizações de segurança",
    "software updates": "Atualizações de software", "web instant messengers": "Mensageiros web",
    "business systems": "Sistemas corporativos", "network protocols": "Protocolos de rede",
    "private protocols": "Protocolos privados", "social networks": "Redes sociais",
    "video conferencing": "Videoconferência", "cloud storage": "Armazenamento em nuvem",
    "advertising": "Publicidade", "e-commerce": "Compras online", "news": "Notícias",
}


def _bytes(valor):
    valor = valor or 0
    if valor >= 1e9:
        return f"{_num(valor / 1e9)} GB"
    if valor >= 1e6:
        return f"{_num(valor / 1e6, 0)} MB"
    return f"{_num(valor / 1e3, 0)} KB"


def _catalogo(conexao, tipo):
    return {l["id"]: l["nome"] for l in conexao.execute("SELECT id, nome FROM catalogo WHERE tipo = ?", (tipo,))}


def _dias(inicio, fim):
    return inicio.astimezone(FUSO).date().isoformat(), fim.astimezone(FUSO).date().isoformat()


def _dados_consumo(conexao, host_id, inicio, fim):
    linhas = conexao.execute(
        "SELECT dia, SUM(download_bytes) AS d, SUM(upload_bytes) AS u FROM internet_dia "
        "WHERE host_id = ? AND dia BETWEEN ? AND ? GROUP BY dia ORDER BY dia", (host_id, *_dias(inicio, fim))
    ).fetchall()
    if not linhas:
        return None
    maior = max(linhas, key=lambda l: l["d"] or 0)
    return {
        "dias": [(l["dia"][8:10] + "/" + l["dia"][5:7], (l["d"] or 0) / 1e9, (l["u"] or 0) / 1e9) for l in linhas],
        "download": sum(l["d"] or 0 for l in linhas),
        "upload": sum(l["u"] or 0 for l in linhas),
        "media": sum(l["d"] or 0 for l in linhas) / len(linhas),
        "maior_dia": maior["dia"][8:10] + "/" + maior["dia"][5:7], "maior_valor": maior["d"] or 0,
    }


def _dados_aplicativos(conexao, host_id, inicio, fim):
    linhas = conexao.execute(
        "SELECT categoria_id AS cat, aplicativo_id AS app, SUM(download_bytes) AS d, SUM(upload_bytes) AS u, "
        "MAX(dispositivos) AS disp FROM aplicativo_dia WHERE host_id = ? AND dia BETWEEN ? AND ? "
        "GROUP BY categoria_id, aplicativo_id", (host_id, *_dias(inicio, fim))
    ).fetchall()
    total = sum((l["d"] or 0) + (l["u"] or 0) for l in linhas)
    if not total:
        return None
    nomes_app, nomes_cat = _catalogo(conexao, "dpi_aplicativo"), _catalogo(conexao, "dpi_categoria")

    def nome_app(cat, app):
        if app == NAO_IDENTIFICADO_APP or cat == NAO_IDENTIFICADO_CAT:
            return "Não identificado"
        return nomes_app.get((cat << 16) | app) or nomes_app.get(app) or f"Aplicativo {app}"

    def nome_cat(cat):
        if cat == NAO_IDENTIFICADO_CAT:
            return "Não identificado"
        nome = nomes_cat.get(cat)
        return CATEGORIAS_PT.get((nome or "").lower(), nome) or f"Categoria {cat}"

    apps = sorted(linhas, key=lambda l: -((l["d"] or 0) + (l["u"] or 0)))
    por_categoria = defaultdict(int)
    for l in linhas:
        por_categoria[l["cat"]] += (l["d"] or 0) + (l["u"] or 0)
    categorias = sorted(por_categoria.items(), key=lambda item: -item[1])
    principais = [(nome_cat(c), v, 100 * v / total) for c, v in categorias[:6]]
    resto = sum(v for _, v in categorias[6:])
    if resto:
        principais.append(("Outras categorias", resto, 100 * resto / total))
    return {
        "total": total,
        "categorias": principais,
        "apps": [{"nome": nome_app(l["cat"], l["app"]), "categoria": nome_cat(l["cat"]),
                  "download": l["d"] or 0, "upload": l["u"] or 0, "dispositivos": l["disp"],
                  "pct": 100 * ((l["d"] or 0) + (l["u"] or 0)) / total} for l in apps[:10]],
    }


def _dados_clientes_detalhe(conexao, host_id, inicio, fim):
    ultimos = {}
    for c in _periodo_sql(conexao, "SELECT * FROM cliente_amostra WHERE host_id = ?", inicio, fim, (host_id,)):
        ultimos[c["mac"]] = c  # fica a foto mais recente de cada cliente
    trafego = conexao.execute(
        "SELECT mac, SUM(download_bytes) AS d, SUM(upload_bytes) AS u FROM cliente_dia "
        "WHERE host_id = ? AND dia BETWEEN ? AND ? GROUP BY mac", (host_id, *_dias(inicio, fim))
    ).fetchall()
    if not ultimos and not trafego:
        return None
    sistemas = _catalogo(conexao, "so")

    def contar(chave):
        contagem = defaultdict(int)
        for c in ultimos.values():
            contagem[chave(c) or "Não identificado"] += 1
        return sorted(contagem.items(), key=lambda item: (-item[1], item[0]))[:5]

    def conexao_txt(c):
        if not c:
            return "-"
        if c["tipo"] == "WIRELESS":
            sinal = f", {c['sinal_dbm']} dBm" if c["sinal_dbm"] is not None else ""
            return f"Wi-Fi {c['ssid'] or ''}{sinal}".replace("Wi-Fi ,", "Wi-Fi,")
        porta = f", porta {c['porta']}" if c["porta"] else ""
        velocidade = f", {c['velocidade_mbps']} Mbps" if c["velocidade_mbps"] else ""
        return f"Cabo{porta}{velocidade}"

    topo = sorted(trafego, key=lambda t: -((t["d"] or 0) + (t["u"] or 0)))[:10]
    macs = set(ultimos) | {t["mac"] for t in trafego}
    return {
        "quantidade": len(macs),
        "conexao": contar(lambda c: "Wi-Fi" if c["tipo"] == "WIRELESS" else "Cabo"),
        "fabricantes": contar(lambda c: c["fabricante"]),
        "tipos": contar(lambda c: c["modelo"]),
        "sistemas": contar(lambda c: sistemas.get(c["so_id"])),
        "topo": [{
            "nome": (ultimos[t["mac"]]["nome"] or t["mac"]) if t["mac"] in ultimos else t["mac"],
            "tipo": ultimos[t["mac"]]["modelo"] if t["mac"] in ultimos else "-",
            "fabricante": ultimos[t["mac"]]["fabricante"] if t["mac"] in ultimos else "-",
            "conexao": conexao_txt(ultimos.get(t["mac"])),
            "download": t["d"] or 0, "upload": t["u"] or 0,
        } for t in topo],
    }


def _bloco_consumo(consumo):
    if not consumo:
        return ""
    kpis = "".join([
        _kpi("Download no período", _bytes(consumo["download"])),
        _kpi("Upload no período", _bytes(consumo["upload"])),
        _kpi("Média diária de download", _bytes(consumo["media"])),
        _kpi("Dia de maior consumo", consumo["maior_dia"], _bytes(consumo["maior_valor"]) + " de download"),
    ])
    rotulos = [d[0] for d in consumo["dias"]]
    return (
        '<section class="painel"><div class="painel-topo"><h2>Consumo da internet</h2>'
        '<span class="meta">total do site por dia</span></div>'
        f'<div class="kpis kpis-4">{kpis}</div>'
        + graficos.barras_duplas(rotulos, [d[1] for d in consumo["dias"]], [d[2] for d in consumo["dias"]],
                                 rotulo="Download e upload por dia")
        + f'<div class="legenda">{_ponto("down")}<span>Download</span>{_ponto("up")}<span>Upload</span></div>'
        '<div class="espaco"></div></section>'
    )


def _bloco_aplicativos(aplicativos):
    if not aplicativos:
        return ""
    categorias = "".join(
        f'<li><span class="cat-nome">{escape(nome)}</span><span class="cat-barra"><i style="width:{pct:.1f}%"></i></span>'
        f'<span class="cat-valor">{_num(pct, 0)}%</span></li>'
        for nome, _valor, pct in aplicativos["categorias"]
    )
    linhas = "".join(
        f'<tr><td class="nome">{escape(a["nome"])}</td><td class="area">{escape(a["categoria"])}</td>'
        f'<td class="num">{_bytes(a["download"])}</td><td class="num">{_bytes(a["upload"])}</td>'
        f'<td class="num">{a["dispositivos"] if a["dispositivos"] is not None else "-"}</td>'
        f'<td class="num">{_num(a["pct"])}%</td></tr>'
        for a in aplicativos["apps"]
    )
    return (
        '<section class="painel painel-quebra"><div class="painel-topo"><h2>Aplicativos na rede</h2>'
        '<span class="meta">total da rede, sem detalhe por pessoa</span></div>'
        f'<ul class="cat-lista">{categorias}</ul>'
        '<table class="tabela tabela-compacta"><thead><tr><th>Aplicativo</th><th>Categoria</th>'
        '<th class="num">Download</th><th class="num">Upload</th><th class="num">Dispositivos</th>'
        f'<th class="num">Participação</th></tr></thead><tbody>{linhas}</tbody></table></section>'
    )


def _bloco_clientes(clientes):
    if not clientes:
        return ""

    def mini(titulo, itens):
        if not itens:
            return ""
        linhas = "".join(f'<li><span>{escape(str(nome))}</span><span class="qtd">{qtd}</span></li>' for nome, qtd in itens)
        return f'<div class="mini"><h3>{titulo}</h3><ul class="contagem">{linhas}</ul></div>'

    resumo = "".join([mini("Conexão", clientes["conexao"]), mini("Tipos de dispositivo", clientes["tipos"]),
                      mini("Fabricantes", clientes["fabricantes"])])
    linhas = "".join(
        f'<tr><td class="nome">{escape(t["nome"] or "-")}</td><td>{escape(t["tipo"] or "-")}</td>'
        f'<td>{escape(t["fabricante"] or "-")}</td><td>{escape(t["conexao"])}</td>'
        f'<td class="num">{_bytes(t["download"])}</td><td class="num">{_bytes(t["upload"])}</td></tr>'
        for t in clientes["topo"]
    )
    tabela = ""
    if linhas:
        tabela = ('<table class="tabela tabela-compacta"><thead><tr><th>Cliente</th><th>Tipo</th><th>Fabricante</th>'
                  '<th>Conexão</th><th class="num">Download</th><th class="num">Upload</th></tr></thead>'
                  f'<tbody>{linhas}</tbody></table><div class="rodape-painel">Tráfego de cada dispositivo na rede '
                  '(rede local e internet), segundo os relatórios do próprio console.</div>')
    return (
        '<section class="painel painel-quebra"><div class="painel-topo"><h2>Clientes</h2>'
        f'<span class="meta">{clientes["quantidade"]} dispositivos no período</span></div>'
        f'<div class="grade-3">{resumo}</div>{tabela}</section>'
    )


CSS = """
:root, .tema-escuro {
  --canvas: #131416; --painel: #1b1d20; --painel-2: #212327; --borda: #2c2f34;
  --texto: #e8e9eb; --texto-2: #a3a8ae; --texto-3: #6f747b;
  --acento: #4797ff; --ok: #3fcb76; --atencao: #f0b43c; --critico: #f2555a;
  --neutro: #5d636b; --parcial: #3b3f45; --vazio: #26292d; --grade: #2a2d32; --upload: #a77bff;
}
.tema-claro {
  --canvas: #f3f4f6; --painel: #ffffff; --painel-2: #f8f9fa; --borda: #e2e5e9;
  --texto: #1c1f23; --texto-2: #5b6168; --texto-3: #8b9097;
  --acento: #006fff; --ok: #1f9d55; --atencao: #c98a0b; --critico: #d93a3f;
  --neutro: #a1a7ae; --parcial: #d3d7dc; --vazio: #eceef1; --grade: #eceef1; --upload: #7a4fe0;
}
@page { size: A4; margin: 0; }
* { box-sizing: border-box; }
html { background: var(--canvas); -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; background: var(--canvas); color: var(--texto); font-size: 14px; line-height: 1.5;
  font-family: "Inter", "Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, Roboto, Arial, sans-serif;
  font-variant-numeric: tabular-nums; }
.pagina { max-width: 960px; margin: 0 auto; padding: 32px 24px;
  -webkit-box-decoration-break: clone; box-decoration-break: clone; }
h1, h2 { font-weight: 600; line-height: 1.2; margin: 0; }
h2 { font-size: 16px; }

.barra { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 16px;
  background: var(--painel); border: 1px solid var(--borda); border-radius: 8px; padding: 12px 16px;
  margin-bottom: 16px; box-shadow: inset 0 1px 0 rgba(255,255,255,0.04); }
.marca { font-weight: 600; font-size: 16px; }
.logo { max-height: 32px; max-width: 180px; display: block; }
.barra-titulo { color: var(--texto-2); font-weight: 500; }
.barra-periodo { justify-self: end; color: var(--texto-2); }

.painel { background: var(--painel); border: 1px solid var(--borda); border-radius: 8px;
  margin-bottom: 16px; overflow: hidden; break-inside: avoid; page-break-inside: avoid;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.04); }
.painel-quebra { break-inside: auto; page-break-inside: auto;
  -webkit-box-decoration-break: clone; box-decoration-break: clone; }
.painel > svg, .painel > .legenda, .painel > .kpis, .painel > .nota-rodape,
.painel > .vazio-texto, .painel > .passos { margin-left: 16px; margin-right: 16px; }
.painel > svg { width: calc(100% - 32px); margin-top: 16px; }
.painel-topo { display: flex; justify-content: space-between; align-items: baseline; gap: 16px;
  padding: 12px 16px; border-bottom: 1px solid var(--borda); }
.meta, .nota-rodape, .kpi-detalhe, footer { font-size: 12px; color: var(--texto-3); line-height: 1.4; }
.nota-rodape { margin-top: 4px; margin-bottom: 16px; }
.vazio-texto { color: var(--texto-2); margin: 16px; }

.tabela { width: 100%; border-collapse: collapse; }
.tabela th { text-align: left; font-weight: 600; font-size: 14px; color: var(--texto);
  padding: 12px 16px; border-bottom: 1px solid var(--borda); }
.tabela td { padding: 12px 16px; border-bottom: 1px solid var(--borda); vertical-align: top; color: var(--texto); }
.tabela tbody tr:last-child td { border-bottom: 0; }
.tabela tr { break-inside: avoid; page-break-inside: avoid; }
.tabela .num { text-align: right; white-space: nowrap; }
.tabela .nome { font-weight: 500; white-space: nowrap; }
.tabela .sev, .tabela .area { white-space: nowrap; color: var(--texto-2); }
.tabela-site td { font-size: 14px; }
.tabela-compacta th, .tabela-compacta td { padding-left: 12px; padding-right: 12px; }
.tabela-compacta th:first-child, .tabela-compacta td:first-child { padding-left: 16px; }
.tabela-compacta th:last-child, .tabela-compacta td:last-child { padding-right: 16px; }
.rodape-painel { font-size: 12px; color: var(--texto-2); padding: 12px 16px; border-top: 1px solid var(--borda); }
.titulo { font-weight: 500; }
.secundario { color: var(--texto-2); margin-top: 4px; }
.acao { color: var(--acento); font-weight: 500; }
.apagado { color: var(--texto-3); }

.ponto { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 8px;
  vertical-align: 1px; background: var(--neutro); }
.ponto.ok { background: var(--ok); } .ponto.atencao { background: var(--atencao); }
.ponto.critico { background: var(--critico); } .ponto.parcial { background: var(--parcial); }
.ponto.down { background: var(--acento); } .ponto.up { background: var(--upload); }

.situacao { display: flex; align-items: baseline; font-size: 16px; margin: 0 0 16px 4px; }

.visao { display: grid; grid-template-columns: 232px 1fr; gap: 16px; break-inside: avoid; page-break-inside: avoid; }
.visao > .painel { margin-bottom: 16px; }
.trilho { padding: 16px; }
.trilho h2 { font-size: 14px; color: var(--texto-2); font-weight: 500; margin-bottom: 12px; }
.trilho h2.separado { margin-top: 24px; padding-top: 16px; border-top: 1px solid var(--borda); }
.contagem { list-style: none; margin: 0; padding: 0; }
.contagem li { display: flex; align-items: baseline; padding: 6px 0; }
.contagem .qtd { margin-left: auto; padding-left: 8px; color: var(--texto-2); white-space: nowrap; }

.legenda { display: flex; gap: 16px; flex-wrap: wrap; align-items: baseline; font-size: 12px; color: var(--texto-2); margin-top: 12px; }
.kpis { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-top: 16px; margin-bottom: 16px; }
.visao > .painel-link { display: flex; flex-direction: column; }
.visao > .painel-link > .kpis { margin-top: auto; padding-top: 16px; }
.kpi { border: 1px solid var(--borda); background: var(--painel-2); border-radius: 6px; padding: 12px; }
.kpi-rotulo { color: var(--texto-2); font-size: 12px; line-height: 1.4; }
.kpi-valor { font-size: 19px; font-weight: 600; line-height: 1.25; margin-top: 4px; }

.passos { margin-top: 16px; margin-bottom: 16px; padding-left: 20px; }
.passos li { padding: 0 0 12px 4px; break-inside: avoid; page-break-inside: avoid; }
.passos li::marker { color: var(--texto-3); }

.g-grade { stroke: var(--grade); stroke-width: 1; }
.g-rotulo { fill: var(--texto-3); font-size: 11px; font-family: inherit; }
.g-barra { fill: var(--acento); } .g-barra-alerta { fill: var(--critico); } .g-barra-parcial { fill: var(--parcial); }
.g-marca { fill: var(--texto-3); }
.g-limite { stroke: var(--critico); stroke-width: 1; stroke-dasharray: 4 3; opacity: .8; }
.g-linha { fill: none; stroke: var(--acento); stroke-width: 2; }
.g-ponto { fill: var(--acento); }
.g-down { fill: var(--acento); } .g-up { fill: var(--upload); }
.kpis-4 { grid-template-columns: repeat(4, 1fr); margin-left: 16px; margin-right: 16px; }
.espaco { height: 16px; }
.legenda span + .ponto { margin-left: 8px; }
.cat-lista { list-style: none; margin: 16px; padding: 0; }
.cat-lista li { display: grid; grid-template-columns: 200px 1fr 48px; align-items: center; gap: 12px; padding: 4px 0; }
.cat-barra { height: 8px; background: var(--vazio); border-radius: 4px; overflow: hidden; }
.cat-barra i { display: block; height: 100%; background: var(--acento); border-radius: 4px; }
.cat-valor { text-align: right; color: var(--texto-2); }
.grade-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; padding: 16px; border-bottom: 1px solid var(--borda); }
.mini h3 { font-size: 12px; font-weight: 500; color: var(--texto-2); margin: 0 0 4px; line-height: 1.4; }
.mini .contagem li { padding: 4px 0; }
.faixa { margin: 16px 16px 0; }
.faixa-barras { display: flex; gap: 3px; height: 56px; }
.faixa-barras span { flex: 1; border-radius: 2px; background: var(--vazio); }
.faixa-rotulos { display: flex; gap: 3px; margin-top: 8px; }
.faixa-rotulos span { flex: 1; min-width: 0; display: flex; justify-content: center; white-space: nowrap;
  font-size: 12px; color: var(--texto-3); line-height: 1.4; }
.faixa .s-ok { background: var(--ok); } .faixa .s-atencao { background: var(--atencao); }
.faixa .s-critico { background: var(--critico); } .faixa .s-parcial { background: var(--parcial); }
.faixa .s-vazio { background: var(--vazio); }

footer { margin: 8px 4px 0; max-width: 75ch; }

@media print { .pagina { max-width: none; padding: 10mm 10mm 12mm; } }
@media (max-width: 720px) {
  .visao { grid-template-columns: 1fr; }
  .kpis, .kpis-4 { grid-template-columns: repeat(2, 1fr); }
  .grade-3 { grid-template-columns: 1fr; }
  .cat-lista li { grid-template-columns: 120px 1fr 40px; }
  .barra { grid-template-columns: 1fr; } .barra-periodo { justify-self: start; }
  .tabela { display: block; overflow-x: auto; }
}
"""


def gerar_html(conexao, console, inicio, fim, marca):
    host_id = console["host_id"]
    todos, _erros = avaliar(conexao, inicio, fim)
    achados = [a for a in todos if a.host_id == host_id]
    link = _dados_link(conexao, host_id, inicio, fim)
    equipamentos = _dados_equipamentos(conexao, host_id, inicio, fim)
    clientes = _dados_clientes(conexao, host_id, inicio, fim)
    detalhe = _dados_clientes_detalhe(conexao, host_id, inicio, fim)
    consumo = _dados_consumo(conexao, host_id, inicio, fim)
    aplicativos = _dados_aplicativos(conexao, host_id, inicio, fim)
    periodo = f"{inicio.astimezone(FUSO):%d/%m/%Y} a {fim.astimezone(FUSO):%d/%m/%Y}"
    tema = "tema-claro" if marca.get("tema") == "claro" else "tema-escuro"
    classe_situacao, texto_situacao = _situacao(achados)
    marca_html = marca["logo_html"] or f'<span class="marca">{escape(marca.get("empresa", ""))}</span>'
    contato = f" Contato: {escape(marca['contato'])}." if marca.get("contato") else ""

    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Saúde da rede - {escape(console['nome'] or '')} - {periodo}</title>
<style>{CSS}</style></head>
<body class="{tema}"><div class="pagina">
<header class="barra">{marca_html}<div class="barra-titulo">Relatório de saúde da rede</div>
<div class="barra-periodo">{periodo}</div></header>
{_bloco_site(console)}
<p class="situacao">{_ponto(classe_situacao)}{texto_situacao}</p>
<div class="visao">{_bloco_trilho(achados, equipamentos, clientes, detalhe)}{_bloco_link(link)}</div>
{_bloco_achados(achados)}
{_bloco_passos(achados)}
{_bloco_graficos(link)}
{_bloco_consumo(consumo)}
{_bloco_aplicativos(aplicativos)}
{_bloco_clientes(detalhe)}
{_bloco_dispositivos(equipamentos, clientes)}
<footer>Relatório preparado por {escape(marca.get('empresa', ''))}.{contato} A disponibilidade do link
é estimada pelas horas com dados registrados na nuvem da Ubiquiti.</footer>
</div></body></html>"""
