"""Mostra os pontos de atenção do período, por console.

Uso (na pasta do projeto, com o ambiente virtual ativo):
    python ver_achados.py            (últimos 30 dias)
    python ver_achados.py --dias 7   (últimos 7 dias)
"""
import argparse
import textwrap
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from achados.regras import FUSO, avaliar
from banco.banco import conectar

ROTULO = {"alta": "ALTA", "media": "MÉDIA", "baixa": "BAIXA", "info": "INFO"}


def _paragrafo(texto):
    return textwrap.fill(texto, width=100, initial_indent="    ", subsequent_indent="      ")


def main():
    parser = argparse.ArgumentParser(description="Mostra os achados do período.")
    parser.add_argument("--dias", type=int, default=30, help="tamanho do período em dias (padrão 30)")
    args = parser.parse_args()

    fim = datetime.now(timezone.utc)
    inicio = fim - timedelta(days=args.dias)

    conexao = conectar()
    try:
        achados, erros = avaliar(conexao, inicio, fim)
        nomes = {}
        for linha in conexao.execute("SELECT host_id, nome FROM console_estado ORDER BY coletado_em"):
            nomes[linha["host_id"]] = linha["nome"]
    finally:
        conexao.close()

    print(f"Achados de {inicio.astimezone(FUSO):%d/%m/%Y} a {fim.astimezone(FUSO):%d/%m/%Y} ({args.dias} dias)")

    por_console = defaultdict(list)
    for a in achados:
        por_console[a.host_id].append(a)

    for host_id, lista in sorted(por_console.items(), key=lambda item: nomes.get(item[0]) or ""):
        print("\n" + "=" * 100)
        print(nomes.get(host_id) or host_id)
        nomes_sev = {"alta": "alta", "media": "média", "baixa": "baixa", "info": "informativo"}
        contagem = [f"{sum(1 for a in lista if a.severidade == s)} {nomes_sev[s]}"
                    for s in ROTULO if any(a.severidade == s for a in lista)]
        print("Pontos de atenção: " + ", ".join(contagem))
        for a in lista:
            print(f"\n  [{ROTULO[a.severidade]}] {a.area}: {a.titulo}")
            print(_paragrafo("Evidência: " + a.evidencia))
            print(_paragrafo("Recomendação: " + a.recomendacao))

    sem_achados = sorted(n for h, n in nomes.items() if h not in por_console and n)
    if sem_achados:
        print("\nSem achados no período: " + ", ".join(sem_achados))
    if not achados:
        print("\nNenhum achado no período.")
    if erros:
        print("\nRegras com erro (os demais achados continuam válidos):")
        for erro in erros:
            print("  - " + erro)


if __name__ == "__main__":
    main()
