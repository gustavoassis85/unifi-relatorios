"""Cliente da api.ui.com usado pelo sistema (Site Manager e connector).

Mesmas regras do coletor/api.py do MVP, mais algumas travas:
- só leitura: GET apenas nos caminhos de GET_PERMITIDOS; POST apenas nos relatórios de
  consumo (POST_PERMITIDOS), que são consultas que a API só aceita por POST;
- a chave vem por parâmetro (cada cliente do MSP tem a sua) e nunca aparece em
  mensagem de erro, log ou repr;
- certificado sempre verificado; não segue redirecionamento (a chave iria junto);
- caminho com "..", "?", "#", "%" ou barra invertida é recusado;
- respeita o Retry-After do erro 429 e um prazo total por chamada;
- resposta maior que 10 MB é recusada.
"""
import json
import re
import time

import requests
from django.views.decorators.debug import sensitive_variables

BASE_URL = "https://api.ui.com"
_CONSOLE = r"^/v1/connector/consoles/[^/]+"

GET_PERMITIDOS = (
    re.compile(r"^/v1/hosts$"),
    re.compile(r"^/v1/sites$"),
    re.compile(r"^/v1/devices$"),
    re.compile(r"^/v1/isp-metrics/(5m|1h)$"),
    re.compile(_CONSOLE + r"/network/integration/v1/[A-Za-z0-9/_-]+$"),     # API oficial
    re.compile(_CONSOLE + r"/network/v2/api/site/[^/]+/clients/active$"),   # clientes conectados
    re.compile(_CONSOLE + r"/network/v2/api/site/[^/]+/traffic$"),          # tráfego por aplicativo
    re.compile(_CONSOLE + r"/network/v2/api/fingerprint_devices/0$"),       # base de identificação
)

POST_PERMITIDOS = (
    re.compile(_CONSOLE + r"/network/api/s/[^/]+/stat/report/(daily\.(site|user)|hourly\.site)$"),
)

_PROIBIDO_NO_CAMINHO = re.compile(r"\.\.|[?#%\\\s]")

MAX_TENTATIVAS = 3
TEMPO_CONEXAO = 10
TEMPO_LEITURA = 25
PRAZO_PADRAO = 120          # segundos, somando tentativas e esperas
MAX_BYTES = 10 * 1024 * 1024
MAX_PAGINAS = 100           # trava contra laço infinito na paginação


class ErroApi(Exception):
    """Erro ao falar com a api.ui.com. A mensagem já vem em português, sem a chave.

    codigo: chave_recusada, sem_permissao, limite, rede, tempo, servidor, resposta, caminho.
    """

    def __init__(self, codigo, mensagem):
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem


def _conferir(caminho, permitidos):
    if not isinstance(caminho, str) or _PROIBIDO_NO_CAMINHO.search(caminho):
        raise ErroApi("caminho", "Caminho não permitido.")
    if not any(p.match(caminho) for p in permitidos):
        raise ErroApi("caminho", f"Caminho não permitido: {caminho}")


def _espera_pedida(resposta):
    """Retry-After do erro 429, entre 1 e 60 segundos."""
    try:
        return min(max(float(resposta.headers.get("Retry-After", "")), 1.0), 60.0)
    except ValueError:
        return 10.0


def _ler_json(resposta, caminho):
    tamanho = resposta.headers.get("Content-Length")
    if tamanho and tamanho.isdigit() and int(tamanho) > MAX_BYTES:
        raise ErroApi("resposta", f"Resposta grande demais em {caminho}.")
    partes, total = [], 0
    for parte in resposta.iter_content(64 * 1024):
        total += len(parte)
        if total > MAX_BYTES:
            raise ErroApi("resposta", f"Resposta grande demais em {caminho}.")
        partes.append(parte)
    try:
        return json.loads(b"".join(partes))
    except ValueError:
        raise ErroApi("resposta", f"Resposta inesperada (não é JSON) em {caminho}.") from None


class ClienteUniFi:
    """Fala com a api.ui.com usando a chave de um cliente do MSP."""

    @sensitive_variables("chave")
    def __init__(self, chave, *, prazo=PRAZO_PADRAO, sessao=None):
        if not chave or not isinstance(chave, str):
            raise ErroApi("chave_recusada", "Chave da UniFi não informada.")
        self.__chave = chave
        self.prazo = prazo
        self._sessao = sessao or requests.Session()
        self._sessao.trust_env = False  # ignora proxy e .netrc do ambiente

    def __repr__(self):
        return "<ClienteUniFi chave=****>"

    # Leitura ----------------------------------------------------------------

    def get(self, caminho, parametros=None):
        _conferir(caminho, GET_PERMITIDOS)
        return self._requisitar("GET", caminho, parametros=parametros)

    def consultar_relatorio(self, caminho, corpo):
        _conferir(caminho, POST_PERMITIDOS)
        return self._requisitar("POST", caminho, corpo=corpo)

    def listar_hosts(self):
        """Todos os consoles da conta, seguindo a paginação (nextToken)."""
        hosts, parametros = [], {"pageSize": 100}
        for _ in range(MAX_PAGINAS):
            resposta = self.get("/v1/hosts", parametros)
            if not isinstance(resposta, dict):
                raise ErroApi("resposta", "Resposta inesperada em /v1/hosts.")
            hosts.extend(h for h in resposta.get("data") or [] if isinstance(h, dict))
            proximo = resposta.get("nextToken")
            if not proximo:
                break
            parametros["nextToken"] = proximo
        return hosts

    # Interno ----------------------------------------------------------------

    @sensitive_variables()
    def _requisitar(self, metodo, caminho, parametros=None, corpo=None):
        if metodo not in ("GET", "POST"):
            raise ErroApi("caminho", "Método não permitido.")
        limite = time.monotonic() + self.prazo

        def esperar(segundos, codigo, mensagem):
            if time.monotonic() + segundos >= limite:
                raise ErroApi(codigo, mensagem)
            time.sleep(segundos)

        for tentativa in range(1, MAX_TENTATIVAS + 1):
            restante = limite - time.monotonic()
            if restante <= 0:
                raise ErroApi("tempo", "A UniFi demorou demais para responder. Tente de novo.")
            try:
                resposta = self._sessao.request(
                    metodo,
                    BASE_URL + caminho,
                    headers={"X-API-Key": self.__chave, "Accept": "application/json"},
                    params=parametros,
                    json=corpo,
                    timeout=(min(TEMPO_CONEXAO, restante), min(TEMPO_LEITURA, restante)),
                    verify=True,
                    allow_redirects=False,
                    stream=True,
                )
            except requests.Timeout:
                if tentativa == MAX_TENTATIVAS:
                    raise ErroApi("tempo", "A UniFi demorou demais para responder. Tente de novo.") from None
                esperar(2 * tentativa, "tempo", "A UniFi demorou demais para responder. Tente de novo.")
                continue
            except requests.RequestException as erro:
                mensagem = f"Falha de rede ao falar com a UniFi ({erro.__class__.__name__})."
                if tentativa == MAX_TENTATIVAS:
                    raise ErroApi("rede", mensagem) from None
                esperar(2 * tentativa, "rede", mensagem)
                continue

            with resposta:
                status = resposta.status_code
                if status == 200:
                    return _ler_json(resposta, caminho)
                if status == 429:
                    esperar(
                        _espera_pedida(resposta),
                        "limite",
                        "A UniFi pediu para esperar (limite de chamadas). Tente de novo em um minuto.",
                    )
                    continue
                if status in (500, 502, 503, 504) and tentativa < MAX_TENTATIVAS:
                    esperar(2 * tentativa, "servidor", f"A UniFi está com problema (erro {status}).")
                    continue
                if status == 401:
                    raise ErroApi("chave_recusada", "A UniFi recusou a chave (401). Confira ou gere uma nova em unifi.ui.com.")
                if status == 403:
                    raise ErroApi("sem_permissao", f"A chave não tem permissão para {caminho} (403).")
                if 300 <= status < 400:
                    raise ErroApi("resposta", f"A UniFi respondeu com redirecionamento ({status}); por segurança, não foi seguido.")
                if status >= 500:
                    raise ErroApi("servidor", f"A UniFi está com problema (erro {status}).")
                raise ErroApi("resposta", f"Erro {status} ao chamar {caminho}.")

        raise ErroApi("limite", "A UniFi pediu para esperar (limite de chamadas). Tente de novo em um minuto.")


# Resumo dos consoles -----------------------------------------------------------

def _versao_do_app(estado, nome_app):
    for app in estado.get("controllers") or []:
        if isinstance(app, dict) and app.get("name") == nome_app:
            return app.get("version") or ""
    return ""


def resumir_host(host):
    """Só os campos que o sistema guarda de cada console.

    LGPD: o /v1/hosts também traz e-mail do dono, localização e usuários; nada disso sai daqui.
    """
    estado = host.get("reportedState") or {}
    if not isinstance(estado, dict):
        estado = {}
    hardware = estado.get("hardware") or {}
    tipo = host.get("type") or ""
    if tipo == "network-server":
        versao_network = estado.get("version") or ""
    else:
        versao_network = _versao_do_app(estado, "network")
    return {
        "host_id": str(host.get("id") or ""),
        "nome": str(estado.get("name") or estado.get("hostname") or "")[:150],
        "modelo": str(hardware.get("name") or "")[:100],
        "tipo": str(tipo)[:50],
        "conectado": estado.get("state") == "connected",
        "firmware": str(hardware.get("firmwareVersion") or "")[:50],
        "versao_network": str(versao_network)[:50],
    }


def resumir_hosts(hosts):
    return [r for r in (resumir_host(h) for h in hosts) if r["host_id"]]
