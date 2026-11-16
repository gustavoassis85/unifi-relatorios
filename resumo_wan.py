"""Mostra um resumo por dia das métricas de link gravadas no banco.

Uso (na pasta do projeto, com o ambiente virtual ativo):  python resumo_wan.py
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from banco.banco import conectar

# Horário de Brasília. O Brasil não tem horário de verão desde 2019, então o fuso é fixo.
FUSO = timezone(timedelta(hours=-3))


def _media(valores):
    valores = [v for v in valores if v is not None]
    return sum(valores) / len(valores) if valores else None


def _maximo(valores):
    valores = [v for v in valores if v is not None]
    return max(valores) if valores else None


def _fmt(valor, sufixo=""):
    return "-" if valor is None else f"{valor:.1f}{sufixo}"


def main():
    conexao = conectar()
    linhas = conexao.execute("SELECT * FROM wan_hora ORDER BY host_id, site_id, horario").fetchall()
    conexao.close()

    if not linhas:
        print("Nenhuma métrica de WAN no banco. Rode antes: python coletar.py")
        return

    # Agrupa por link (console + site) e, dentro dele, por dia no horário de Brasília.
    links = defaultdict(lambda: defaultdict(list))
    for linha in linhas:
        horario = datetime.fromisoformat(linha["horario"].replace("Z", "+00:00")).astimezone(FUSO)
        links[(linha["host_id"], linha["site_id"])][horario.date()].append(linha)

    for (host_id, site_id), dias in links.items():
        provedor = next((l["provedor"] for d in dias.values() for l in d if l["provedor"]), "?")
        print(f"\nLink {provedor} | console {host_id[:12]}... | site {site_id}")
        print(f"{'Dia':<12}{'Horas':>6}{'Lat. média':>12}{'Perda média':>13}{'Pior hora':>11}{'Uptime':>9}")
        for dia, horas in sorted(dias.items()):
            print(
                f"{dia.strftime('%d/%m/%Y'):<12}"
                f"{len(horas):>6}"
                f"{_fmt(_media(h['latencia_media'] for h in horas), ' ms'):>12}"
                f"{_fmt(_media(h['perda_pct'] for h in horas), '%'):>13}"
                f"{_fmt(_maximo(h['perda_pct'] for h in horas), '%'):>11}"
                f"{_fmt(_media(h['uptime_pct'] for h in horas), '%'):>9}"
            )


if __name__ == "__main__":
    main()
