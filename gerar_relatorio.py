"""Gera o relatório de saúde da rede (HTML pronto para virar PDF) de cada console.

Uso (na pasta do projeto, com o ambiente virtual ativo):
    python gerar_relatorio.py                    (últimos 30 dias, todos os consoles)
    python gerar_relatorio.py --mes 2026-10      (mês fechado)
    python gerar_relatorio.py --console "Dream"  (só consoles com esse nome)

Os relatórios ficam em dados/relatorios/ (fora do Git, porque têm dados de cliente)
e abrem sozinhos no navegador. Para gerar o PDF: Ctrl+P > Salvar como PDF.
"""
import argparse
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from achados.regras import FUSO, _dt
from banco.banco import conectar
from relatorio.gerar import carregar_marca, gerar_html

PASTA_SAIDA = Path(__file__).resolve().parent / "dados" / "relatorios"


def _periodo(args):
    if args.mes:
        ano, mes = (int(x) for x in args.mes.split("-"))
        inicio = datetime(ano, mes, 1, tzinfo=FUSO)
        proximo = datetime(ano + (mes == 12), mes % 12 + 1, 1, tzinfo=FUSO)
        return inicio, proximo - timedelta(seconds=1)
    fim = datetime.now(timezone.utc)
    return fim - timedelta(days=args.dias), fim


def _nome_arquivo(texto):
    return re.sub(r"[^A-Za-z0-9_-]+", "-", texto).strip("-") or "console"


def main():
    parser = argparse.ArgumentParser(description="Gera o relatório de saúde da rede.")
    parser.add_argument("--dias", type=int, default=30, help="últimos N dias (padrão 30)")
    parser.add_argument("--mes", help="mês fechado no formato AAAA-MM (ex.: 2026-10)")
    parser.add_argument("--console", help="gera só para consoles cujo nome contém este texto")
    parser.add_argument("--nao-abrir", action="store_true", help="não abre o navegador no final")
    args = parser.parse_args()

    inicio, fim = _periodo(args)
    marca = carregar_marca()
    conexao = conectar()
    try:
        consoles = conexao.execute(
            "SELECT * FROM console_estado c WHERE tipo = 'console' AND coletado_em = "
            "(SELECT MAX(coletado_em) FROM console_estado WHERE host_id = c.host_id) ORDER BY nome"
        ).fetchall()
        # Relatório só para quem esteve conectado no período (registros antigos ficam de fora).
        consoles = [c for c in consoles if c["conectado"]
                    or (c["mudou_estado_em"] and _dt(c["mudou_estado_em"]) >= inicio.astimezone(FUSO))]
        if args.console:
            consoles = [c for c in consoles if args.console.lower() in (c["nome"] or "").lower()]
        if not consoles:
            print("Nenhum console para gerar relatório no período.")
            return

        PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
        rotulo = args.mes or f"{inicio.astimezone(FUSO):%Y-%m-%d}_a_{fim.astimezone(FUSO):%Y-%m-%d}"
        for console in consoles:
            arquivo = PASTA_SAIDA / f"{_nome_arquivo(console['nome'] or 'console')}_{rotulo}.html"
            arquivo.write_text(gerar_html(conexao, console, inicio, fim, marca), encoding="utf-8")
            print(f"Relatório gerado: {arquivo}")
            if not args.nao_abrir and hasattr(os, "startfile"):
                os.startfile(arquivo)  # abre no navegador padrão (Windows)
    finally:
        conexao.close()


if __name__ == "__main__":
    main()
