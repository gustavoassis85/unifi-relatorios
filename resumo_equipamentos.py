"""Mostra a situação mais recente dos equipamentos gravada no banco.

Uso (na pasta do projeto, com o ambiente virtual ativo):  python resumo_equipamentos.py
"""
from datetime import datetime, timedelta, timezone

from banco.banco import conectar

# Horário de Brasília. O Brasil não tem horário de verão desde 2019, então o fuso é fixo.
FUSO = timezone(timedelta(hours=-3))

ULTIMAS_AMOSTRAS = """
SELECT e.*, s.nome AS site_nome,
       (SELECT nome FROM console_estado c WHERE c.host_id = e.host_id
        ORDER BY coletado_em DESC LIMIT 1) AS console_nome
FROM equipamento_amostra e
LEFT JOIN site_network s ON s.host_id = e.host_id AND s.site_id = e.site_id
WHERE e.coletado_em = (SELECT MAX(coletado_em) FROM equipamento_amostra WHERE device_id = e.device_id)
ORDER BY console_nome, site_nome, e.nome
"""

ULTIMOS_CLIENTES = """
SELECT * FROM clientes_amostra c
WHERE coletado_em = (SELECT MAX(coletado_em) FROM clientes_amostra
                     WHERE host_id = c.host_id AND site_id = c.site_id)
"""


def _ultimo_detalhe(conexao, tabela, device_id):
    """Linhas da coleta de detalhe mais recente do equipamento (portas ou rádios)."""
    return conexao.execute(
        f"SELECT * FROM {tabela} WHERE device_id = ? AND coletado_em = "
        f"(SELECT MAX(coletado_em) FROM {tabela} WHERE device_id = ?)",
        (device_id, device_id),
    ).fetchall()


def _taxa(bps):
    if bps is None:
        return "-"
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.1f} Mbps"
    return f"{bps / 1000:.1f} kbps"


def _fmt(valor, sufixo=""):
    return "-" if valor is None else f"{valor:.1f}{sufixo}"


def main():
    conexao = conectar()
    equipamentos = conexao.execute(ULTIMAS_AMOSTRAS).fetchall()
    if not equipamentos:
        conexao.close()
        print("Nenhum equipamento no banco. Rode antes: python coletar.py")
        return

    clientes = {(c["host_id"], c["site_id"]): c for c in conexao.execute(ULTIMOS_CLIENTES)}
    coleta = datetime.fromisoformat(equipamentos[0]["coletado_em"]).astimezone(FUSO)
    print(f"Equipamentos (coleta de {coleta.strftime('%d/%m/%Y %H:%M')})")

    site_atual = None
    for e in equipamentos:
        site = (e["host_id"], e["site_id"])
        if site != site_atual:
            site_atual = site
            print(f"\n{e['console_nome'] or 'Console'} | site {e['site_nome'] or e['site_id']}")
            c = clientes.get(site)
            if c:
                print(f"  Clientes conectados: {c['total']} ({c['cabo']} cabo, {c['wifi']} Wi-Fi)")

        print(f"\n  {e['nome'] or '(sem nome)'} - {e['modelo'] or '?'} - {e['estado'] or '?'}")

        firmware = f"Firmware {e['firmware'] or '-'}"
        if e["firmware_atualizavel"]:
            firmware += " (atualização disponível)"
        if e["uptime_seg"] is not None:
            firmware += f" | ligado há {e['uptime_seg'] // 86400} dias"
        print(f"    {firmware}")

        if e["cpu_pct"] is not None:
            print(
                f"    CPU {_fmt(e['cpu_pct'], '%')} | memória {_fmt(e['memoria_pct'], '%')} | "
                f"carga {_fmt(e['carga_1min'])}"
            )
            print(
                f"    Uplink no momento: {_taxa(e['uplink_tx_bps'])} enviando, "
                f"{_taxa(e['uplink_rx_bps'])} recebendo"
            )

        portas_ativas = [p for p in _ultimo_detalhe(conexao, "porta_estado", e["device_id"])
                         if p["estado"] == "UP"]
        if portas_ativas:
            textos = []
            for p in portas_ativas:
                texto = f"{p['idx']} ({p['velocidade_mbps']} de {p['velocidade_max_mbps']} Mbps"
                if (p["velocidade_mbps"] or 0) < (p["velocidade_max_mbps"] or 0):
                    texto += ", abaixo da capacidade"
                textos.append(texto + ")")
            print(f"    Portas ativas: {', '.join(textos)}")

        retransmissao = {
            r["posicao"]: r["retransmissao_pct"]
            for r in conexao.execute(
                "SELECT posicao, retransmissao_pct FROM radio_amostra "
                "WHERE device_id = ? AND coletado_em = ?",
                (e["device_id"], e["coletado_em"]),
            )
        }
        for r in _ultimo_detalhe(conexao, "radio_config", e["device_id"]):
            canal = f"canal {r['canal']}"
            if not r["canal"]:
                canal += " (desligado ou sem dado)"
            print(
                f"    Wi-Fi {r['frequencia_ghz']:g} GHz: {r['padrao'] or '?'}, {canal}, "
                f"{r['largura_mhz']} MHz, retransmissão {_fmt(retransmissao.get(r['posicao']), '%')}"
            )

    conexao.close()


if __name__ == "__main__":
    main()
