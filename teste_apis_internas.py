"""Teste das APIs internas do UniFi Network pelo connector (somente leitura, não grava nada).

Verifica se a chave da nuvem dá acesso a:
1. clientes conectados com fabricante, tipo, rede Wi-Fi, sinal e consumo (v2 clients/active);
2. base de identificação de dispositivos, para traduzir o código do sistema operacional;
3. relatórios diários guardados pelo próprio console: consumo da internet do site e consumo por
   cliente (stat/report). São consultas de leitura, mas essa API exige o método POST.

Uso (na pasta do projeto, com o ambiente virtual ativo):  python teste_apis_internas.py
"""
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

from banco.banco import conectar

FUSO = timezone(timedelta(hours=-3))


def _gb(valor):
    return f"{(valor or 0) / 1e9:.2f} GB".replace(".", ",")


def _console_e_site():
    conexao = conectar()
    console = conexao.execute(
        "SELECT host_id, nome FROM console_estado c WHERE conectado = 1 AND tipo = 'console' "
        "AND coletado_em = (SELECT MAX(coletado_em) FROM console_estado WHERE host_id = c.host_id) LIMIT 1"
    ).fetchone()
    site = None
    if console:
        site = conexao.execute(
            "SELECT referencia FROM site_network WHERE host_id = ? LIMIT 1", (console["host_id"],)
        ).fetchone()
    conexao.close()
    return console, (site["referencia"] if site and site["referencia"] else "default")


def main():
    load_dotenv()
    chave = os.getenv("UNIFI_API_KEY")
    if not chave:
        sys.exit("Chave não encontrada no .env.")
    console, site = _console_e_site()
    if not console:
        sys.exit("Nenhum console conectado no banco. Rode antes: python coletar.py")
    base = f"https://api.ui.com/v1/connector/consoles/{console['host_id']}/network"
    cabecalhos = {"X-API-Key": chave, "Accept": "application/json"}

    def chamar(metodo, caminho, corpo=None):
        resposta = requests.request(metodo, base + caminho, headers=cabecalhos, json=corpo, timeout=30)
        try:
            return resposta.status_code, resposta.json()
        except ValueError:
            return resposta.status_code, None

    agora = datetime.now(timezone.utc)
    periodo = {"start": int((agora - timedelta(days=30)).timestamp() * 1000), "end": int(agora.timestamp() * 1000)}
    print(f"Console: {console['nome']} | site: {site}\n")

    # 1. Clientes conectados (v2)
    status, dados = chamar("GET", f"/v2/api/site/{site}/clients/active")
    print(f"[1] Clientes conectados (v2): HTTP {status}")
    if status == 200 and isinstance(dados, list):
        for c in dados:
            fp = c.get("fingerprint") or {}
            print(f"  - {c.get('display_name') or c.get('hostname')} | {c.get('type')} | "
                  f"fabricante: {c.get('oui')} | tipo: {c.get('model_name')} | código do SO: {fp.get('os_name')}")
            if c.get("type") == "WIRELESS":
                print(f"    Wi-Fi {c.get('essid')} | sinal {c.get('signal')} dBm | experiência "
                      f"{c.get('wifi_experience_score')} | retransmissão {c.get('wifi_tx_retries_percentage')}%")
            else:
                print(f"    cabo: porta {c.get('sw_port')} a {c.get('wired_rate_mbps')} Mbps")
            print(f"    contadores desde a conexão: tx {_gb(c.get('tx_bytes'))} | rx {_gb(c.get('rx_bytes'))} | "
                  f"conectado há {round((c.get('uptime') or 0) / 3600, 1)} h")

    # 2. Base de identificação de dispositivos (para traduzir o sistema operacional)
    status, dados = chamar("GET", "/v2/api/fingerprint_devices/0")
    print(f"\n[2] Base de identificação: HTTP {status}")
    if status == 200 and isinstance(dados, dict):
        for chave_bloco, valor in list(dados.items())[:8]:
            tamanho = len(valor) if hasattr(valor, "__len__") else "-"
            amostra = list(valor.items())[:3] if isinstance(valor, dict) else (valor[:2] if isinstance(valor, list) else valor)
            print(f"  - {chave_bloco}: {type(valor).__name__} com {tamanho} itens; exemplo: {str(amostra)[:220]}")

    # 3. Consumo da internet do site por dia
    corpo = {"attrs": ["time", "wan-rx_bytes", "wan-tx_bytes", "num_sta"], **periodo}
    status, dados = chamar("POST", f"/api/s/{site}/stat/report/daily.site", corpo)
    print(f"\n[3] Consumo diário da internet do site: HTTP {status}")
    if status == 200 and isinstance(dados, dict):
        dias = dados.get("data", [])
        print(f"  {len(dias)} dia(s) no relatório. Últimos 7:")
        for d in dias[-7:]:
            dia = datetime.fromtimestamp(d.get("time", 0) / 1000, FUSO).strftime("%d/%m")
            print(f"  - {dia}: download {_gb(d.get('wan-rx_bytes'))} | upload {_gb(d.get('wan-tx_bytes'))} | "
                  f"clientes {d.get('num_sta')}")

    # 4. Consumo por cliente por dia
    corpo = {"attrs": ["time", "rx_bytes", "tx_bytes", "user"], **periodo}
    status, dados = chamar("POST", f"/api/s/{site}/stat/report/daily.user", corpo)
    print(f"\n[4] Consumo diário por cliente: HTTP {status}")
    if status == 200 and isinstance(dados, dict):
        linhas = dados.get("data", [])
        print(f"  {len(linhas)} registro(s). Campos do primeiro: {sorted(linhas[0].keys()) if linhas else '-'}")
        total = defaultdict(lambda: [0, 0])
        for l in linhas:
            total[l.get("user")][0] += l.get("tx_bytes") or 0
            total[l.get("user")][1] += l.get("rx_bytes") or 0
        for usuario, (tx, rx) in sorted(total.items(), key=lambda item: -item[1][0])[:5]:
            print(f"  - {usuario}: tx {_gb(tx)} | rx {_gb(rx)} (30 dias)")


if __name__ == "__main__":
    main()
