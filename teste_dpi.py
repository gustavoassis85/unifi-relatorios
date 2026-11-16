"""Teste do DPI (tráfego por aplicativo e categoria) pelo connector. Somente leitura, não grava nada.

Verifica:
1. tráfego por aplicativo da tela nova do UniFi (v2 traffic), últimos 7 dias;
2. DPI do site por categoria e por aplicativo (stat/sitedpi; leitura, mas a API exige POST);
3. catálogo oficial de aplicativos e categorias (API Network oficial), para traduzir os códigos.

Uso (na pasta do projeto, com o ambiente virtual ativo):  python teste_dpi.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

from banco.banco import conectar


def _gb(valor):
    return f"{(valor or 0) / 1e9:.2f} GB".replace(".", ",")


def _resumo(valor, limite=300):
    """Mostra a estrutura de uma resposta desconhecida sem despejar tudo na tela."""
    if isinstance(valor, dict):
        return "dict com chaves " + str(list(valor.keys())[:12]) + " | exemplo: " + str(valor)[:limite]
    if isinstance(valor, list):
        return f"lista com {len(valor)} itens | primeiro: " + (str(valor[0])[:limite] if valor else "-")
    return str(valor)[:limite]


def main():
    load_dotenv()
    chave = os.getenv("UNIFI_API_KEY")
    if not chave:
        sys.exit("Chave não encontrada no .env.")
    conexao = conectar()
    console = conexao.execute(
        "SELECT c.host_id, c.nome, s.referencia FROM console_estado c "
        "LEFT JOIN site_network s ON s.host_id = c.host_id "
        "WHERE c.conectado = 1 AND c.tipo = 'console' "
        "AND c.coletado_em = (SELECT MAX(coletado_em) FROM console_estado WHERE host_id = c.host_id) LIMIT 1"
    ).fetchone()
    conexao.close()
    if not console:
        sys.exit("Nenhum console conectado no banco. Rode antes: python coletar.py")
    site = console["referencia"] or "default"
    base = f"https://api.ui.com/v1/connector/consoles/{console['host_id']}/network"
    cabecalhos = {"X-API-Key": chave, "Accept": "application/json"}

    def chamar(metodo, caminho, corpo=None, parametros=None):
        resposta = requests.request(metodo, base + caminho, headers=cabecalhos, json=corpo,
                                    params=parametros, timeout=30)
        try:
            return resposta.status_code, resposta.json()
        except ValueError:
            return resposta.status_code, None

    agora = datetime.now(timezone.utc)
    inicio = int((agora - timedelta(days=7)).timestamp() * 1000)
    fim = int(agora.timestamp() * 1000)
    print(f"Console: {console['nome']} | site: {site}\n")

    # 1. Tela nova de tráfego (v2)
    status, dados = chamar("GET", f"/v2/api/site/{site}/traffic",
                           parametros={"start": inicio, "end": fim, "includeUnidentified": "true"})
    print(f"[1] Tráfego por aplicativo (v2 traffic, 7 dias): HTTP {status}")
    if dados is not None:
        print("  " + _resumo(dados, 600))
        if isinstance(dados, dict):
            for chave_bloco, valor in list(dados.items())[:6]:
                print(f"  - {chave_bloco}: {_resumo(valor, 250)}")

    # 2. DPI do site por categoria e por aplicativo
    for tipo in ("by_cat", "by_app"):
        status, dados = chamar("POST", f"/api/s/{site}/stat/sitedpi", corpo={"type": tipo})
        print(f"\n[2] DPI do site ({tipo}): HTTP {status}")
        if status == 200 and isinstance(dados, dict):
            blocos = dados.get("data") or []
            itens = (blocos[0].get(tipo) if blocos and isinstance(blocos[0], dict) else None) or []
            print(f"  {len(itens)} item(ns). Campos: {sorted(itens[0].keys()) if itens else '-'}")
            itens = sorted(itens, key=lambda i: -((i.get('rx_bytes') or 0) + (i.get('tx_bytes') or 0)))
            for i in itens[:10]:
                print(f"  - cat {i.get('cat')} app {i.get('app')}: recebido {_gb(i.get('rx_bytes'))} | "
                      f"enviado {_gb(i.get('tx_bytes'))}")
        elif dados is not None:
            print("  " + _resumo(dados))

    # 3. Catálogo oficial para traduzir os códigos
    for nome, caminho in (("categorias", "/integration/v1/dpi/categories"),
                          ("aplicativos", "/integration/v1/dpi/applications")):
        status, dados = chamar("GET", caminho, parametros={"limit": 5})
        print(f"\n[3] Catálogo oficial de {nome}: HTTP {status}")
        if dados is not None:
            print("  " + _resumo(dados, 400))


if __name__ == "__main__":
    main()
