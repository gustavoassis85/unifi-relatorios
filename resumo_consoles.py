"""Mostra a situação mais recente de cada console gravada no banco.

Uso (na pasta do projeto, com o ambiente virtual ativo):  python resumo_consoles.py
"""
from datetime import datetime, timedelta, timezone

from banco.banco import conectar

# Horário de Brasília. O Brasil não tem horário de verão desde 2019, então o fuso é fixo.
FUSO = timezone(timedelta(hours=-3))

ULTIMA_FOTO = """
SELECT * FROM console_estado c
WHERE coletado_em = (SELECT MAX(coletado_em) FROM console_estado WHERE host_id = c.host_id)
ORDER BY conectado DESC, nome
"""


def _data(texto_iso):
    """Converte a data da API para horário de Brasília. Devolve None se vier vazia."""
    if not texto_iso:
        return None
    return datetime.fromisoformat(texto_iso.replace("Z", "+00:00")).astimezone(FUSO)


def _dias_atras(data):
    return (datetime.now(FUSO) - data).days


def main():
    conexao = conectar()
    consoles = conexao.execute(ULTIMA_FOTO).fetchall()
    conexao.close()

    if not consoles:
        print("Nenhum console no banco. Rode antes: python coletar.py")
        return

    coleta = _data(consoles[0]["coletado_em"])
    print(f"Situação dos consoles (coleta de {coleta.strftime('%d/%m/%Y %H:%M')})")

    for c in consoles:
        print(f"\n{c['nome'] or '(sem nome)'} - {c['modelo'] or c['tipo']}")

        desde = _data(c["mudou_estado_em"])
        situacao = "Online" if c["conectado"] else "Offline"
        if desde:
            situacao += f" desde {desde.strftime('%d/%m/%Y')} ({_dias_atras(desde)} dias)"
        print(f"  Estado: {situacao}")

        versoes = []
        if c["versao_os"]:
            versoes.append(f"UniFi OS {c['versao_os']}")
        if c["versao_network"]:
            versoes.append(f"Network {c['versao_network']}")
        print(f"  Versões: {' | '.join(versoes) or '-'}")

        if c["tipo"] != "network-server":
            if c["atualizacao_disponivel"]:
                print(f"  Atualização: pendente (UniFi OS {c['atualizacao_disponivel']})")
            else:
                print("  Atualização: nenhuma pendente")

        backup = _data(c["ultimo_backup"])
        if backup:
            print(f"  Último backup em nuvem: {backup.strftime('%d/%m/%Y')} ({_dias_atras(backup)} dias)")
        else:
            print("  Último backup em nuvem: sem registro")


if __name__ == "__main__":
    main()
