"""Gráficos simples em SVG, gerados em Python (sem bibliotecas), para o relatório."""
import math
from html import escape

LARGURA, ALTURA = 680, 210
MARGEM_ESQ, MARGEM_DIR, MARGEM_TOPO, MARGEM_BASE = 46, 12, 14, 34


def _num(valor, casas=1):
    texto = f"{valor:.{casas}f}"
    if "." in texto:
        texto = texto.rstrip("0").rstrip(".")
    return texto.replace(".", ",")


def _teto(valor):
    """Arredonda para cima até um número "redondo" (1, 2, 2,5, 5 x 10^n) para o eixo Y."""
    if valor <= 0:
        return 1
    base = 10 ** math.floor(math.log10(valor))
    for fator in (1, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if valor <= fator * base:
            return fator * base
    return 10 * base


def _eixos(maximo, sufixo):
    """Linhas de grade horizontais e rótulos do eixo Y."""
    altura_util = ALTURA - MARGEM_TOPO - MARGEM_BASE
    partes = []
    for fracao in (0, 0.5, 1):
        y = MARGEM_TOPO + altura_util * (1 - fracao)
        partes.append(
            f'<line x1="{MARGEM_ESQ}" y1="{y:.1f}" x2="{LARGURA - MARGEM_DIR}" y2="{y:.1f}" '
            f'stroke="#e3e3e3" stroke-width="1"/>'
            f'<text x="{MARGEM_ESQ - 6}" y="{y + 4:.1f}" text-anchor="end" font-size="10" '
            f'fill="#666">{_num(maximo * fracao, 0 if maximo >= 10 else 2)}{sufixo}</text>'
        )
    return "".join(partes)


def _rotulos_x(rotulos, posicoes):
    """Mostra no máximo ~8 rótulos no eixo X para não embolar."""
    passo = max(1, round(len(rotulos) / 8))
    return "".join(
        f'<text x="{x:.1f}" y="{ALTURA - MARGEM_BASE + 20}" text-anchor="middle" font-size="10" '
        f'fill="#666">{escape(r)}</text>'
        for i, (r, x) in enumerate(zip(rotulos, posicoes)) if i % passo == 0 or i == len(rotulos) - 1
    )


def barras(rotulos, valores, cor, limite=None, sufixo="%", marcados=(), parciais=()):
    """Gráfico de barras. Barras acima do limite ficam vermelhas; dias em 'parciais' (com poucos
    dados) ficam cinza claro; dias em 'marcados' ganham um triângulo cinza na base."""
    if not valores:
        return ""
    maximo = _teto(max([v for v in valores if v is not None] + [limite or 0, 0.1]) * 1.1)
    altura_util = ALTURA - MARGEM_TOPO - MARGEM_BASE
    largura_util = LARGURA - MARGEM_ESQ - MARGEM_DIR
    passo = largura_util / len(valores)
    largura_barra = max(2, passo * 0.7)

    partes, centros = [_eixos(maximo, sufixo)], []
    for i, valor in enumerate(valores):
        centro = MARGEM_ESQ + passo * (i + 0.5)
        centros.append(centro)
        if valor is not None:
            h = altura_util * valor / maximo
            y = MARGEM_TOPO + altura_util - h
            if rotulos[i] in parciais:
                preenchimento = "#c5cbd3"
            elif limite is not None and valor >= limite:
                preenchimento = "#c62828"
            else:
                preenchimento = cor
            partes.append(
                f'<rect x="{centro - largura_barra / 2:.1f}" y="{y:.1f}" width="{largura_barra:.1f}" '
                f'height="{h:.1f}" fill="{preenchimento}" rx="1"/>'
            )
        if rotulos[i] in marcados:
            base = MARGEM_TOPO + altura_util
            partes.append(
                f'<polygon points="{centro - 4:.1f},{base + 7:.1f} {centro + 4:.1f},{base + 7:.1f} '
                f'{centro:.1f},{base + 1:.1f}" fill="#888"/>'
            )
    if limite is not None:
        y = MARGEM_TOPO + altura_util * (1 - limite / maximo)
        partes.append(
            f'<line x1="{MARGEM_ESQ}" y1="{y:.1f}" x2="{LARGURA - MARGEM_DIR}" y2="{y:.1f}" '
            f'stroke="#c62828" stroke-width="1" stroke-dasharray="4 3"/>'
        )
    partes.append(_rotulos_x(rotulos, centros))
    return f'<svg viewBox="0 0 {LARGURA} {ALTURA}" width="100%" role="img">{"".join(partes)}</svg>'


def linha(rotulos, valores, cor, sufixo=" ms"):
    """Gráfico de linha simples (pontos sem valor interrompem a linha)."""
    if not valores or all(v is None for v in valores):
        return ""
    maximo = _teto(max(v for v in valores if v is not None) * 1.15)
    altura_util = ALTURA - MARGEM_TOPO - MARGEM_BASE
    largura_util = LARGURA - MARGEM_ESQ - MARGEM_DIR
    passo = largura_util / len(valores)

    partes, centros, trecho = [_eixos(maximo, sufixo)], [], []
    trechos = []
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
        partes.append(f'<polyline points="{pontos}" fill="none" stroke="{cor}" stroke-width="2"/>')
        partes.extend(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.2" fill="{cor}"/>' for x, y in t)
    partes.append(_rotulos_x(rotulos, centros))
    return f'<svg viewBox="0 0 {LARGURA} {ALTURA}" width="100%" role="img">{"".join(partes)}</svg>'
