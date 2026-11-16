"""Roda todas as coletas. Se uma falhar, as outras continuam.

Uso (na pasta do projeto, com o ambiente virtual ativo):  python coletar.py
Para refazer agora as coletas periódicas (consumo e catálogos), buscando de novo os 30 dias:
    python coletar.py --forcar
Cada execução também fica registrada em dados/coleta.log (útil quando roda pelo agendador).
"""
import sys
from datetime import datetime
from pathlib import Path

from banco.banco import conectar

from coletor import catalogos, clientes, consoles, consumo, equipamentos, wan
from coletor.api import ErroApi

ARQUIVO_LOG = Path(__file__).resolve().parent / "dados" / "coleta.log"

# Cada passo novo do projeto acrescenta sua coleta aqui.
# A de consoles vem primeiro: a de equipamentos usa a lista de consoles conectados.
COLETAS = [
    ("Consoles (situação, versões, backup)", consoles.coletar),
    ("WAN (métricas do link)", wan.coletar),
    ("Equipamentos (saúde, portas, Wi-Fi, clientes)", equipamentos.coletar),
    ("Clientes conectados (fabricante, sistema, Wi-Fi)", clientes.coletar),
    ("Consumo (internet, clientes e aplicativos por dia)", consumo.coletar),
    ("Catálogos (nomes de aplicativos e sistemas)", catalogos.coletar),
]


def _registrar(linhas):
    """Mostra as linhas na tela e grava no arquivo de log com data e hora."""
    ARQUIVO_LOG.parent.mkdir(exist_ok=True)
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    with open(ARQUIVO_LOG, "a", encoding="utf-8") as log:
        for linha in linhas:
            print(linha)
            log.write(f"{agora} {linha}\n")


def main():
    if "--forcar" in sys.argv:
        conexao = conectar()
        with conexao:
            conexao.execute("DELETE FROM controle_coleta")
        conexao.close()
        consumo.BUSCAR_HISTORICO = True
    linhas, falhas = [], 0
    for nome, funcao in COLETAS:
        try:
            linhas.append(f"[ok]    {nome}: {funcao()}")
        except ErroApi as erro:
            falhas += 1
            linhas.append(f"[falha] {nome}: {erro}")
        except Exception as erro:  # qualquer outro problema não derruba as demais coletas
            falhas += 1
            linhas.append(f"[falha] {nome}: erro inesperado ({erro.__class__.__name__}: {erro})")

    linhas.append(f"{falhas} coleta(s) com falha." if falhas else "Todas as coletas concluídas.")
    _registrar(linhas)
    if falhas:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
