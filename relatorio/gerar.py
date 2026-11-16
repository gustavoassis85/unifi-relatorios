"""Monta o relatório mensal de saúde da rede (HTML pronto para imprimir em PDF) de um console.

O relatório segue a tríade DPS: Disponibilidade, Produtividade e Segurança.
Tudo fica num arquivo HTML só (gráficos em SVG e logo embutidos), que abre em qualquer navegador.
"""
import base64
import json
from collections import defaultdict
from datetime import timedelta
from html import escape
from pathlib import Path
from statistics import mean

from achados.regras import FUSO, LIMITES, PILARES, _chave, _dt, avaliar, notas
from relatorio import graficos

PASTA = Path(__file__).resolve().parent
ROTULO = {"alta": "Alta", "media": "Média", "baixa": "Baixa", "info": "Informativo"}
COR_SEVERIDADE = {"alta": "#c62828", "media": "#b26a00", "baixa": "#5f6b7a", "info": "#8a94a3"}


def carregar_marca():
    marca = json.loads((PASTA / "marca.json").read_text(encoding="utf-8"))
    logo = marca.get("logo")
    marca["logo_html"] = ""
    if logo and Path(logo).is_file():
        tipo = "svg+xml" if logo.lower().endswith(".svg") else "png"
        dados = base64.b64encode(Path(logo).read_bytes()).decode()
        marca["logo_html"] = f'<img class="logo" src="data:image/{tipo};base64,{dados}" alt="">'
    return marca


def _num(valor, casas=1):
    return "-" if valor is None else f"{valor:.{casas}f}".replace(".", ",")


def _pontos(n):
    if n == 0:
        return "nenhum ponto de atenção"
    return "1 ponto de atenção" if n == 1 else f"{n} pontos de atenção"


def _cor_nota(nota):
    return "#2e7d32" if nota >= 90 else "#b26a00" if nota >= 70 else "#c62828"


def _situacao_geral(nota):
    menor = min(nota.values())
    if menor >= 90:
        return "Rede saudável no período, sem pontos críticos."
    if menor >= 70:
        return "Rede funcionando, com pontos de atenção que merecem acompanhamento."
    return "Rede com problemas que pedem ação no próximo mês."


def _periodo_sql(conexao, sql, inicio, fim, parametros, coluna="coletado_em"):
    filtro = f" AND substr({coluna}, 1, 19) >= ? AND substr({coluna}, 1, 19) <= ? ORDER BY {coluna}"
    return conexao.execute(sql + filtro, (*parametros, _chave(inicio), _chave(fim))).fetchall()


# ---------------------------------------------------------------- dados do relatório

def _dados_link(conexao, host_id, inicio, fim):
    horas = _periodo_sql(conexao, "SELECT * FROM wan_hora WHERE host_id = ?", inicio, fim, (host_id,), "horario")
    if not horas:
        return None
    momentos = [_dt(h["horario"]) for h in horas]
    esperadas = int((max(momentos) - min(momentos)).total_seconds() // 3600) + 1
    por_dia = defaultdict(list)
    for h, m in zip(horas, momentos):
        por_dia[m.date()].append(h)

    dia, ultimo = min(momentos).date(), max(momentos).date()
    dias = []
    while dia <= ultimo:
        hs = por_dia.get(dia, [])
        perdas = [h["perda_pct"] for h in hs if h["perda_pct"] is not None]
        latencias = [h["latencia_media"] for h in hs if h["latencia_media"] is not None]
        dias.append({
            "dia": dia, "horas": len(hs),
            "perda": mean(perdas) if perdas else None,
            "latencia": mean(latencias) if latencias else None,
        })
        dia += timedelta(days=1)

    # Primeiro e último dia são naturalmente incompletos; só os do meio contam como "sem dado".
    marcados = {d["dia"].strftime("%d/%m") for d in dias[1:-1] if d["horas"] < 24}
    parciais = {d["dia"].strftime("%d/%m") for d in dias if d["horas"] < LIMITES["perda_min_horas_dia"]}
    perdas = [h["perda_pct"] for h in horas if h["perda_pct"] is not None]
    pior = max(horas, key=lambda h: h["perda_pct"] or 0)
    return {
        "provedor": next((h["provedor"] for h in horas if h["provedor"]), "operadora"),
        "plano": next(((h["download_kbps"], h["upload_kbps"]) for h in horas if h["download_kbps"]), None),
        "esperadas": esperadas,
        "presentes": len(horas),
        "disponibilidade": 100 * len(horas) / esperadas,
        "perda_media": mean(perdas) if perdas else None,
        "pior_hora": pior,
        "latencia_media": mean(h["latencia_media"] for h in horas if h["latencia_media"] is not None),
        "dias": dias,
        "marcados": marcados,
        "parciais": parciais,
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
            "estado": ultima["estado"],
            "online": 100 * sum(1 for a in lista if a["estado"] == "ONLINE") / len(lista),
            "amostras": len(lista),
            "cpu": mean(cpu) if cpu else None,
            "memoria": mean(memoria) if memoria else None,
            "ligado_dias": ultima["uptime_seg"] // 86400 if ultima["uptime_seg"] is not None else None,
        })
    return sorted(resultado, key=lambda e: e["nome"] or "")


def _dados_clientes(conexao, host_id, inicio, fim):
    linhas = _periodo_sql(conexao, "SELECT * FROM clientes_amostra WHERE host_id = ?", inicio, fim, (host_id,))
    if not linhas:
        return None
    return {
        "media": mean(l["total"] for l in linhas),
        "pico": max(l["total"] for l in linhas),
        "pico_wifi": max(l["wifi"] for l in linhas),
        "pico_cabo": max(l["cabo"] for l in linhas),
        "amostras": len(linhas),
    }


# ---------------------------------------------------------------- blocos de HTML

def _bloco_achados(achados):
    if not achados:
        return '<p class="ok">Nenhum ponto de atenção neste pilar.</p>'
    itens = []
    for a in achados:
        itens.append(
            f'<div class="achado" style="border-left-color:{COR_SEVERIDADE[a.severidade]}">'
            f'<div class="achado-topo"><span class="selo" style="background:{COR_SEVERIDADE[a.severidade]}">'
            f'{ROTULO[a.severidade]}</span> <strong>{escape(a.titulo)}</strong></div>'
            f'<p>{escape(a.evidencia)}</p>'
            f'<p class="rec"><span>Recomendação:</span> {escape(a.recomendacao)}</p></div>'
        )
    return "".join(itens)


def _kpi(rotulo, valor, detalhe=""):
    return (f'<div class="kpi"><div class="kpi-valor">{valor}</div><div class="kpi-rotulo">{rotulo}</div>'
            f'{f"<div class=kpi-detalhe>{detalhe}</div>" if detalhe else ""}</div>')


def gerar_html(conexao, console, inicio, fim, marca):
    host_id = console["host_id"]
    todos, erros = avaliar(conexao, inicio, fim)
    achados = [a for a in todos if a.host_id == host_id]
    nota = notas(achados)
    por_pilar = {p: [a for a in achados if a.pilar == p] for p in PILARES}
    link = _dados_link(conexao, host_id, inicio, fim)
    equipamentos = _dados_equipamentos(conexao, host_id, inicio, fim)
    clientes = _dados_clientes(conexao, host_id, inicio, fim)
    cor = marca.get("cor", "#1f5fbf")
    periodo = f"{inicio.astimezone(FUSO):%d/%m/%Y} a {fim.astimezone(FUSO):%d/%m/%Y}"

    # Resumo executivo
    cartoes = "".join(
        f'<div class="nota" style="border-top-color:{_cor_nota(nota[p])}">'
        f'<div class="nota-valor" style="color:{_cor_nota(nota[p])}">{nota[p]}</div>'
        f'<div class="nota-pilar">{p}</div><div class="nota-qtd">'
        f'{_pontos(len([a for a in por_pilar[p] if a.severidade != "info"]))}</div></div>'
        for p in PILARES
    )
    principais = [a for a in achados if a.severidade in ("alta", "media")][:4]
    lista_principais = "".join(f"<li>{escape(a.titulo)}</li>" for a in principais) or \
        "<li>Nenhum ponto relevante no período.</li>"

    # Disponibilidade
    disp_kpis = []
    if link:
        disp_kpis.append(_kpi("Disponibilidade estimada do link", f"{_num(link['disponibilidade'])}%",
                              f"{link['presentes']} de {link['esperadas']} horas com dados"))
    disp_kpis.append(_kpi("Console", "Online" if console["conectado"] else "Offline",
                          escape(console["modelo"] or "")))
    if equipamentos:
        disp_kpis.append(_kpi("Equipamentos online agora",
                              f"{sum(1 for e in equipamentos if e['estado'] == 'ONLINE')} de {len(equipamentos)}"))

    # Produtividade
    prod_kpis, graficos_link = [], ""
    if link:
        pior = link["pior_hora"]
        prod_kpis += [
            _kpi("Perda de pacote média", f"{_num(link['perda_media'])}%",
                 f"pior hora: {_num(pior['perda_pct'], 0)}% em {_dt(pior['horario']):%d/%m %Hh}"),
            _kpi("Latência média", f"{_num(link['latencia_media'])} ms", escape(link["provedor"])),
        ]
        if link["plano"]:
            prod_kpis.append(_kpi("Velocidade contratada",
                                  f"{link['plano'][0] // 1000} / {link['plano'][1] // 1000} Mbps",
                                  "download / upload"))
        rotulos = [d["dia"].strftime("%d/%m") for d in link["dias"]]
        graficos_link = (
            '<h3>Perda de pacote por dia</h3>'
            + graficos.barras(rotulos, [d["perda"] for d in link["dias"]], cor,
                              limite=LIMITES["perda_dia_instavel"], marcados=link["marcados"],
                              parciais=link["parciais"])
            + f'<p class="legenda">Linha tracejada: limite de {_num(LIMITES["perda_dia_instavel"])}% de '
              'perda média no dia; barras vermelhas: dias acima do limite.'
            + (' Barras cinza: dias com poucos dados.' if link["parciais"] else '')
            + (' Triângulo cinza: dia com horas sem nenhum dado do link.' if link["marcados"] else '')
            + '</p>'
            + '<h3>Latência média por dia</h3>'
            + graficos.linha(rotulos, [d["latencia"] for d in link["dias"]], cor)
        )
    if clientes:
        prod_kpis.append(_kpi("Dispositivos conectados", f"{_num(clientes['media'], 0)} em média",
                              f"pico de {clientes['pico']} ({clientes['pico_cabo']} cabo, "
                              f"{clientes['pico_wifi']} Wi-Fi)"))

    tabela_equip = ""
    if equipamentos:
        linhas = "".join(
            f"<tr><td>{escape(e['nome'] or '-')}</td><td>{escape(e['modelo'] or '-')}</td>"
            f"<td>{escape(e['firmware'] or '-')}</td><td>{_num(e['online'])}%</td>"
            f"<td>{_num(e['cpu'])}%</td><td>{_num(e['memoria'])}%</td>"
            f"<td>{'-' if e['ligado_dias'] is None else str(e['ligado_dias']) + ' dias'}</td></tr>"
            for e in equipamentos
        )
        tabela_equip = (
            '<h3>Equipamentos</h3><table><thead><tr><th>Nome</th><th>Modelo</th><th>Firmware</th>'
            '<th>Online</th><th>CPU média</th><th>Memória média</th><th>Ligado há</th></tr></thead>'
            f'<tbody>{linhas}</tbody></table>'
        )

    # Segurança
    seg_kpis = [_kpi("Sistema do console", f"UniFi OS {escape(console['versao_os'] or '-')}",
                     f"atualização disponível: {escape(console['atualizacao_disponivel'].split('+')[0])}"
                     if console["atualizacao_disponivel"] else "sem atualização pendente")]
    if console["ultimo_backup"]:
        backup = _dt(console["ultimo_backup"])
        seg_kpis.append(_kpi("Último backup em nuvem", f"{backup:%d/%m/%Y}",
                             f"{(fim.astimezone(FUSO) - backup).days} dias antes do fim do período"))
    else:
        seg_kpis.append(_kpi("Último backup em nuvem", "Sem registro"))

    recomendacoes = "".join(
        f'<li><strong>{escape(a.titulo)}.</strong> {escape(a.recomendacao)}</li>'
        for a in achados if a.severidade in ("alta", "media")
    ) or "<li>Manter o acompanhamento mensal.</li>"

    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>Relatório de saúde da rede - {escape(console['nome'] or '')} - {periodo}</title>
<style>
  @page {{ size: A4; margin: 14mm 14mm 16mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: "Segoe UI", Arial, sans-serif; color: #1f2933; font-size: 11pt; margin: 0; line-height: 1.45; }}
  .pagina {{ max-width: 820px; margin: 0 auto; padding: 24px; }}
  header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 3px solid {cor}; padding-bottom: 12px; }}
  .logo {{ max-height: 48px; max-width: 200px; }}
  .empresa {{ font-size: 13pt; font-weight: 600; color: {cor}; }}
  h1 {{ font-size: 19pt; margin: 18px 0 2px; }}
  .sub {{ color: #52606d; margin: 0 0 18px; }}
  h2 {{ font-size: 14pt; color: {cor}; border-bottom: 1px solid #d9dee4; padding-bottom: 4px; margin: 28px 0 12px; }}
  h3 {{ font-size: 11pt; margin: 18px 0 6px; color: #323f4b; }}
  .notas {{ display: flex; gap: 12px; }}
  .nota {{ flex: 1; border: 1px solid #d9dee4; border-top: 5px solid; border-radius: 6px; padding: 12px; text-align: center; }}
  .nota-valor {{ font-size: 28pt; font-weight: 700; line-height: 1.1; }}
  .nota-pilar {{ font-weight: 600; }}
  .nota-qtd {{ color: #616e7c; font-size: 9.5pt; }}
  .situacao {{ font-size: 12pt; margin: 14px 0 6px; }}
  .kpis {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 8px; }}
  .kpi {{ flex: 1 1 170px; background: #f5f7fa; border-radius: 6px; padding: 10px 12px; break-inside: avoid; page-break-inside: avoid; }}
  .kpis, .notas, table, svg {{ break-inside: avoid; page-break-inside: avoid; }}
  h3 {{ break-after: avoid; page-break-after: avoid; }}
  .kpi-valor {{ font-size: 15pt; font-weight: 700; }}
  .kpi-rotulo {{ font-size: 9.5pt; color: #3e4c59; }}
  .kpi-detalhe {{ font-size: 9pt; color: #7b8794; }}
  .achado {{ border-left: 4px solid; background: #fafbfc; padding: 8px 12px; margin: 8px 0; border-radius: 0 6px 6px 0; page-break-inside: avoid; }}
  .achado p {{ margin: 4px 0; }}
  .selo {{ color: #fff; font-size: 8.5pt; padding: 1px 7px; border-radius: 10px; margin-right: 4px; }}
  .rec {{ color: #3e4c59; }} .rec span {{ font-weight: 600; }}
  .ok {{ color: #2e7d32; }}
  .legenda {{ font-size: 9pt; color: #7b8794; margin-top: 0; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 9.5pt; }}
  th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #e4e7eb; }}
  th {{ background: #f5f7fa; }}
  ol li {{ margin-bottom: 6px; }}
  footer {{ margin-top: 30px; border-top: 1px solid #d9dee4; padding-top: 8px; font-size: 8.5pt; color: #7b8794; }}
  svg {{ display: block; }}
  section {{ page-break-inside: auto; }}
  @media print {{ .pagina {{ padding: 0; }} h2 {{ page-break-after: avoid; }} }}
</style></head>
<body><div class="pagina">
<header><div>{marca['logo_html'] or f'<span class="empresa">{escape(marca.get("empresa", ""))}</span>'}</div>
<div class="sub" style="margin:0;text-align:right">Relatório mensal de saúde da rede<br>{periodo}</div></header>

<h1>{escape(console['nome'] or 'Rede do cliente')}</h1>
<p class="sub">Análise de disponibilidade, produtividade e segurança da rede no período.</p>

<h2>Resumo executivo</h2>
<div class="notas">{cartoes}</div>
<p class="situacao">{_situacao_geral(nota)}</p>
<h3>Principais pontos</h3><ul>{lista_principais}</ul>

<h2>Disponibilidade</h2>
<div class="kpis">{''.join(disp_kpis)}</div>
{_bloco_achados(por_pilar['Disponibilidade'])}

<h2>Produtividade</h2>
<div class="kpis">{''.join(prod_kpis)}</div>
{graficos_link}
{tabela_equip}
{_bloco_achados(por_pilar['Produtividade'])}

<h2>Segurança</h2>
<div class="kpis">{''.join(seg_kpis)}</div>
{_bloco_achados(por_pilar['Segurança'])}

<h2>Recomendações para o próximo mês</h2>
<ol>{recomendacoes}</ol>

<footer>Relatório preparado por {escape(marca.get('empresa', ''))}{' - ' + escape(marca['contato']) if marca.get('contato') else ''}.
Notas de 0 a 100 por pilar: cada ponto de atenção desconta conforme a gravidade. Disponibilidade do link
estimada pelas horas com dados registrados na nuvem da Ubiquiti.</footer>
</div></body></html>"""
