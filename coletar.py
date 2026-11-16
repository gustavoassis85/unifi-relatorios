"""Roda todas as coletas. Se uma falhar, as outras continuam.

Uso (na pasta do projeto, com o ambiente virtual ativo):  python coletar.py
Cada execução também fica registrada em dados/coleta.log (útil quando roda pelo agendador).
"""
from datetime import datetime
from pathlib import Path

from coletor import consoles, equipamentos, wan
from coletor.api import ErroApi

ARQUIVO_LOG = Path(__file__).resolve().parent / "dados" / "coleta.log"

# Cada passo novo do projeto acrescenta sua coleta aqui.
# A de consoles vem primeiro: a de equipamentos usa a lista de consoles conectados.
COLETAS = [
    ("Consoles (situação, versões, backup)", consoles.coletar),
    ("WAN (métricas do link)", wan.coletar),
    ("Equipamentos (saúde, portas, Wi-Fi, clientes)", equipamentos.coletar),
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
