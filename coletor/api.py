"""Cliente da api.ui.com (Site Manager e connector).

Regras de segurança deste módulo:
- só faz GET (não existe função para alterar nada);
- só chama caminhos da lista CAMINHOS_PERMITIDOS;
- nunca mostra a chave em mensagens ou logs.
"""
import os
import time

import requests
from dotenv import load_dotenv

BASE_URL = "https://api.ui.com"

# Só caminhos que começam com um destes podem ser chamados. Qualquer outro é bloqueado.
CAMINHOS_PERMITIDOS = (
    "/v1/hosts",
    "/v1/sites",
    "/v1/devices",
    "/v1/isp-metrics/",
    "/v1/connector/consoles/",
)

MAX_TENTATIVAS = 3


class ErroApi(Exception):
    """Erro ao falar com a api.ui.com (a mensagem já vem em português)."""


def _chave():
    load_dotenv()
    chave = os.getenv("UNIFI_API_KEY")
    if not chave:
        raise ErroApi("Chave não encontrada. Confira o arquivo .env (linha UNIFI_API_KEY=...).")
    return chave


def _segundos_de_espera(resposta):
    """Lê o Retry-After que a API manda junto com o erro 429 (limite de chamadas)."""
    try:
        return min(max(float(resposta.headers.get("Retry-After", "")), 1.0), 60.0)
    except ValueError:
        return 10.0


def get(caminho, parametros=None):
    """Faz um GET na api.ui.com e devolve o JSON da resposta."""
    if not caminho.startswith(CAMINHOS_PERMITIDOS):
        raise ErroApi(f"Caminho não permitido: {caminho}")
    if caminho.startswith("/v1/connector/") and "/network/integration/v1/" not in caminho:
        raise ErroApi(f"Pelo connector, só a API Network é permitida: {caminho}")

    cabecalhos = {"X-API-Key": _chave(), "Accept": "application/json"}

    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            resposta = requests.get(
                BASE_URL + caminho, headers=cabecalhos, params=parametros, timeout=30
            )
        except requests.RequestException as erro:
            if tentativa == MAX_TENTATIVAS:
                raise ErroApi(
                    f"Falha de rede ao chamar {caminho} ({erro.__class__.__name__})."
                ) from None
            time.sleep(5 * tentativa)
            continue

        if resposta.status_code == 429:
            time.sleep(_segundos_de_espera(resposta))
            continue
        if resposta.status_code in (500, 502, 503, 504) and tentativa < MAX_TENTATIVAS:
            time.sleep(5 * tentativa)
            continue
        if resposta.status_code == 401:
            raise ErroApi("Chave recusada (401). Gere uma nova em unifi.ui.com e atualize o .env.")
        if resposta.status_code == 403:
            raise ErroApi(f"Sem permissão para {caminho} (403).")
        if resposta.status_code != 200:
            raise ErroApi(f"Erro {resposta.status_code} ao chamar {caminho}.")
        return resposta.json()

    raise ErroApi(f"Limite de chamadas atingido em {caminho}, mesmo após {MAX_TENTATIVAS} tentativas.")
