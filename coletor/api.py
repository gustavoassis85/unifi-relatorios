"""Cliente da api.ui.com (Site Manager e connector).

Regras de segurança deste módulo:
- nada aqui altera configuração: só leitura;
- GET apenas em caminhos permitidos (lista abaixo);
- POST apenas nos dois relatórios de consumo do console, que são consultas de leitura mas que a
  API só aceita por POST. Nenhum outro POST é possível;
- nunca mostra a chave em mensagens ou logs.
"""
import os
import re
import time

import requests
from dotenv import load_dotenv

BASE_URL = "https://api.ui.com"
_CONSOLE = r"^/v1/connector/consoles/[^/]+"

# GET: Site Manager e, pelo connector, só estas rotas da aplicação Network.
GET_PERMITIDOS = (
    re.compile(r"^/v1/hosts"),
    re.compile(r"^/v1/sites"),
    re.compile(r"^/v1/devices"),
    re.compile(r"^/v1/isp-metrics/"),
    re.compile(_CONSOLE + r"/network/integration/v1/"),                     # API oficial
    re.compile(_CONSOLE + r"/network/v2/api/site/[^/]+/clients/active$"),   # clientes conectados
    re.compile(_CONSOLE + r"/network/v2/api/site/[^/]+/traffic$"),          # tráfego por aplicativo
    re.compile(_CONSOLE + r"/network/v2/api/fingerprint_devices/0$"),       # base de identificação
)

# POST: somente os relatórios diários de consumo (leitura).
POST_PERMITIDOS = (
    re.compile(_CONSOLE + r"/network/api/s/[^/]+/stat/report/daily\.(site|user)$"),
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


def _requisitar(metodo, caminho, parametros=None, corpo=None):
    cabecalhos = {"X-API-Key": _chave(), "Accept": "application/json"}
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            resposta = requests.request(metodo, BASE_URL + caminho, headers=cabecalhos,
                                        params=parametros, json=corpo, timeout=30)
        except requests.RequestException as erro:
            if tentativa == MAX_TENTATIVAS:
                raise ErroApi(f"Falha de rede ao chamar {caminho} ({erro.__class__.__name__}).") from None
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
        try:
            return resposta.json()
        except ValueError:
            raise ErroApi(f"Resposta inesperada (não é JSON) em {caminho}.") from None

    raise ErroApi(f"Limite de chamadas atingido em {caminho}, mesmo após {MAX_TENTATIVAS} tentativas.")


def get(caminho, parametros=None):
    """GET na api.ui.com, só em caminhos permitidos. Devolve o JSON da resposta."""
    if not any(p.match(caminho) for p in GET_PERMITIDOS):
        raise ErroApi(f"Caminho não permitido: {caminho}")
    return _requisitar("GET", caminho, parametros=parametros)


def consultar_relatorio(caminho, corpo):
    """POST de leitura, permitido só nos relatórios diários de consumo do console."""
    if not any(p.match(caminho) for p in POST_PERMITIDOS):
        raise ErroApi(f"Consulta não permitida: {caminho}")
    return _requisitar("POST", caminho, corpo=corpo)
