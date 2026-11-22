"""Gráficos em SVG, gerados em Python (sem bibliotecas), para o relatório.

As cores vêm das classes CSS do relatório (g-*, s-*), então os gráficos seguem o tema
(escuro ou claro) automaticamente.
"""
import math
from html import escape

LARGURA, ALTURA = 680, 200
MARGEM_ESQ, MARGEM_DIR, MARGEM_TOPO, MARGEM_BASE = 58, 8, 12, 32


def _num(valor, casas=1):
    texto = f"{valor:.{casas}f}"
    if "." in texto:
        texto = texto.rstrip("0").rstrip(".")
    return texto.replace(".", ",")


def _teto(valor):
    """Arredonda para cima até um número "redondo" para o eixo Y."""
    if valor <= 0:
        return 1
    base = 10 ** math.floor(math.log10(valor))
    for fator in (1, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if valor <= fator * base + 1e-9:
            return fator * base
    return 10 * base


def _svg(conteudo, altura=ALTURA, rotulo=""):
    return (f'<svg viewBox="0 0 {LARGURA} {altura}" width="100%" role="img" '
            f'aria-label="{escape(rotulo)}">{conteudo}</svg>')


def _eixos(maximo, sufixo):
    altura_util = ALTURA - MARGEM_TOPO - MARGEM_BASE
    partes = []
    for fracao in (0, 0.5, 1):
        y = MARGEM_TOPO + altura_util * (1 - fracao)
        partes.append(
            f'<line class="g-grade" x1="{MARGEM_ESQ}" y1="{y:.1f}" x2="{LARGURA - MARGEM_DIR}" y2="{y:.1f}"/>'
            f'<text class="g-rotulo" x="{MARGEM_ESQ - 8}" y="{y + 4:.1f}" text-anchor="end">'
            f'{_num(maximo * fracao, 0 if maximo >= 10 else 2)}{sufixo}</text>'
        )
    return "".join(partes)


def _rotulos_x(rotulos, posicoes, y):
    """No máximo ~8 rótulos; o último sempre aparece, e o vizinho próximo dele é omitido."""
    passo = max(1, round(len(rotulos) / 8))
    ultimo = len(rotulos) - 1
    mostrar = [i for i in range(len(rotulos)) if i % passo == 0 and ultimo - i >= max(1, passo // 2 + 1)]
    mostrar.append(ultimo)
    return "".join(
        f'<text class="g-rotulo" x="{posicoes[i]:.1f}" y="{y}" text-anchor="middle">{escape(rotulos[i])}</text>'
        for i in sorted(set(mostrar))
    )


def faixa_dias(rotulos, estados, rotulo=""):
    """Faixa de saúde por dia, no estilo das barras de uptime do UniFi (em HTML, para manter
    o mesmo tamanho na tela e no PDF). estados: 'ok', 'atencao', 'critico', 'parcial' ou 'vazio'."""
    if not estados:
        return ""
    passo = max(1, round(len(rotulos) / 8))
    ultimo = len(rotulos) - 1
    mostrar = {i for i in range(len(rotulos)) if i % passo == 0 and ultimo - i >= max(1, passo // 2 + 1)} | {ultimo}
    barras_html = "".join(f'<span class="s-{e}" title="{escape(r)}"></span>' for r, e in zip(rotulos, estados))
    rotulos_html = "".join(f'<span>{escape(r) if i in mostrar else ""}</span>' for i, r in enumerate(rotulos))
    return (f'<div class="faixa" role="img" aria-label="{escape(rotulo)}">'
            f'<div class="faixa-barras">{barras_html}</div><div class="faixa-rotulos">{rotulos_html}</div></div>')


def barras(rotulos, valores, limite=None, sufixo="%", marcados=(), parciais=(), rotulo="", destaques=()):
    """Barras por dia. Acima do limite: destaque de alerta. Dias em 'parciais' (poucos dados):
    cor neutra. Dias em 'marcados' ganham um triângulo na base (horas sem dado)."""
    if not valores:
        return ""
    maximo = _teto(max([v for v in valores if v is not None] + [limite or 0, 0.1]) * 1.1)
    altura_util = ALTURA - MARGEM_TOPO - MARGEM_BASE
    passo = (LARGURA - MARGEM_ESQ - MARGEM_DIR) / len(valores)
    largura = max(2, passo * 0.62)
    base = MARGEM_TOPO + altura_util

    partes, centros = [_eixos(maximo, sufixo)], []
    for i, valor in enumerate(valores):
        centro = MARGEM_ESQ + passo * (i + 0.5)
        centros.append(centro)
        if valor is not None:
            h = altura_util * valor / maximo
            if rotulos[i] in destaques:
                classe = "g-barra-pico"
            elif rotulos[i] in parciais:
                classe = "g-barra-parcial"
            elif limite is not None and valor >= limite:
                classe = "g-barra-alerta"
            else:
                classe = "g-barra"
            partes.append(f'<rect class="{classe}" x="{centro - largura / 2:.1f}" y="{base - h:.1f}" '
                          f'width="{largura:.1f}" height="{h:.1f}" rx="1.5"/>')
        if rotulos[i] in marcados:
            partes.append(f'<polygon class="g-marca" points="{centro - 4:.1f},{base + 8:.1f} '
                          f'{centro + 4:.1f},{base + 8:.1f} {centro:.1f},{base + 2:.1f}"/>')
    if limite is not None:
        y = MARGEM_TOPO + altura_util * (1 - limite / maximo)
        partes.append(f'<line class="g-limite" x1="{MARGEM_ESQ}" y1="{y:.1f}" '
                      f'x2="{LARGURA - MARGEM_DIR}" y2="{y:.1f}"/>')
    partes.append(_rotulos_x(rotulos, centros, ALTURA - 8))
    return _svg("".join(partes), rotulo=rotulo)


def linha(rotulos, valores, sufixo=" ms", rotulo=""):
    """Linha simples; dias sem valor interrompem a linha."""
    if not valores or all(v is None for v in valores):
        return ""
    maximo = _teto(max(v for v in valores if v is not None) * 1.15)
    altura_util = ALTURA - MARGEM_TOPO - MARGEM_BASE
    passo = (LARGURA - MARGEM_ESQ - MARGEM_DIR) / len(valores)

    partes, centros, trechos, trecho = [_eixos(maximo, sufixo)], [], [], []
    for i, valor in enumerate(valores):
        x = MARGEM_ESQ + passo * (i + 0.5)
        centros.append(x)
        if valor is None:
            if trecho:
                trechos.append(trecho)
            trecho = []
            continue
        trecho.append((x, MARGEM_TOPO + altura_util * (1 - valor / maximo)))
    if trecho:
        trechos.append(trecho)
    for t in trechos:
        pontos = " ".join(f"{x:.1f},{y:.1f}" for x, y in t)
        partes.append(f'<polyline class="g-linha" points="{pontos}"/>')
        partes.extend(f'<circle class="g-ponto" cx="{x:.1f}" cy="{y:.1f}" r="2.5"/>' for x, y in t)
    partes.append(_rotulos_x(rotulos, centros, ALTURA - 8))
    return _svg("".join(partes), rotulo=rotulo)


def barras_duplas(rotulos, valores_a, valores_b, sufixo=" GB", rotulo=""):
    """Duas barras por dia, lado a lado (ex.: download em azul e upload em roxo, como no UniFi)."""
    if not valores_a:
        return ""
    todos = [v for v in list(valores_a) + list(valores_b) if v is not None]
    maximo = _teto(max(todos + [0.01]) * 1.1)
    altura_util = ALTURA - MARGEM_TOPO - MARGEM_BASE
    passo = (LARGURA - MARGEM_ESQ - MARGEM_DIR) / len(valores_a)
    largura = max(1.5, passo * 0.32)
    base = MARGEM_TOPO + altura_util

    partes, centros = [_eixos(maximo, sufixo)], []
    for i, (a, b) in enumerate(zip(valores_a, valores_b)):
        centro = MARGEM_ESQ + passo * (i + 0.5)
        centros.append(centro)
        for valor, classe, x in ((a, "g-down", centro - largura - 0.5), (b, "g-up", centro + 0.5)):
            if valor:
                h = altura_util * valor / maximo
                partes.append(f'<rect class="{classe}" x="{x:.1f}" y="{base - h:.1f}" width="{largura:.1f}" '
                              f'height="{h:.1f}" rx="1"/>')
    partes.append(_rotulos_x(rotulos, centros, ALTURA - 8))
    return _svg("".join(partes), rotulo=rotulo)
