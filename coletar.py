"""Roda todas as coletas. Se uma falhar, as outras continuam.

Uso (na pasta do projeto, com o ambiente virtual ativo):  python coletar.py
"""
from coletor import consoles, wan
from coletor.api import ErroApi

# Cada passo novo do projeto acrescenta sua coleta aqui.
COLETAS = [
    ("Consoles (situação, versões, backup)", consoles.coletar),
    ("WAN (métricas do link)", wan.coletar),
]


def main():
    falhas = 0
    for nome, funcao in COLETAS:
        try:
            print(f"[ok]    {nome}: {funcao()}")
        except ErroApi as erro:
            falhas += 1
            print(f"[falha] {nome}: {erro}")
        except Exception as erro:  # qualquer outro problema não derruba as demais coletas
            falhas += 1
            print(f"[falha] {nome}: erro inesperado ({erro.__class__.__name__}: {erro})")

    if falhas:
        print(f"\n{falhas} coleta(s) com falha.")
        raise SystemExit(1)
    print("\nTodas as coletas concluídas.")


if __name__ == "__main__":
    main()
