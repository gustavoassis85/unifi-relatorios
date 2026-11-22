"""Testes do cliente da api.ui.com, com respostas simuladas (nada vai para a internet)."""
import json

import pytest
import requests

from unifi import api
from unifi.api import ClienteUniFi, ErroApi, resumir_hosts

CHAVE = "chave-secreta-de-teste-0000-ZZZZ"
HOST_ID = "AC8BA9590D19000000000709CC8000000000075E7C0E00000000638880EA:1907547615"


class Resposta:
    def __init__(self, status=200, corpo=None, cabecalhos=None, bruto=None):
        self.status_code = status
        self.headers = cabecalhos or {}
        self._bruto = bruto if bruto is not None else json.dumps(corpo or {}).encode()

    def iter_content(self, tamanho):
        for i in range(0, len(self._bruto), tamanho):
            yield self._bruto[i:i + tamanho]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class SessaoFalsa:
    """Devolve as respostas da fila, na ordem, e anota cada chamada."""

    def __init__(self, *respostas):
        self.fila = list(respostas)
        self.chamadas = []
        self.trust_env = True

    def request(self, metodo, url, **opcoes):
        self.chamadas.append({"metodo": metodo, "url": url, **opcoes})
        item = self.fila.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def sem_espera(monkeypatch):
    """Esperas (Retry-After, novas tentativas) não dormem de verdade; o relógio anda."""
    relogio = {"agora": 1000.0}
    monkeypatch.setattr(api.time, "monotonic", lambda: relogio["agora"])
    monkeypatch.setattr(api.time, "sleep", lambda s: relogio.__setitem__("agora", relogio["agora"] + s))
    return relogio


def cliente(*respostas, prazo=120):
    sessao = SessaoFalsa(*respostas)
    return ClienteUniFi(CHAVE, prazo=prazo, sessao=sessao), sessao


# Caminhos e métodos ----------------------------------------------------------

@pytest.mark.parametrize("caminho", [
    "/v1/hosts",
    "/v1/isp-metrics/1h",
    f"/v1/connector/consoles/{HOST_ID}/network/integration/v1/sites",
    f"/v1/connector/consoles/{HOST_ID}/network/v2/api/site/default/clients/active",
])
def test_get_em_caminho_permitido(caminho):
    c, sessao = cliente(Resposta(corpo={"data": []}))
    assert c.get(caminho) == {"data": []}
    assert sessao.chamadas[0]["metodo"] == "GET"


@pytest.mark.parametrize("caminho", [
    "/v1/outra-coisa",
    "/v1/hosts/../connector",
    "/v1/hosts?x=1",
    "/v1/hosts#x",
    "/v1/isp-metrics/1h%2F..",
    f"/v1/connector/consoles/{HOST_ID}/network/api/s/default/rest/user",
    f"/v1/connector/consoles/{HOST_ID}/network/integration/v1/../../api/s/default/cmd/devmgr",
    f"/v1/connector/consoles/{HOST_ID}/network/v2/api/site/default/clients/active/x",
    "https://outro-site.com/v1/hosts",
])
def test_get_recusa_caminho_fora_da_lista(caminho):
    c, sessao = cliente()
    with pytest.raises(ErroApi) as erro:
        c.get(caminho)
    assert erro.value.codigo == "caminho"
    assert sessao.chamadas == []


def test_post_so_nos_relatorios_de_consumo():
    caminho = f"/v1/connector/consoles/{HOST_ID}/network/api/s/default/stat/report/daily.site"
    c, sessao = cliente(Resposta(corpo={"data": []}))
    c.consultar_relatorio(caminho, {"attrs": ["time"]})
    assert sessao.chamadas[0]["metodo"] == "POST"


@pytest.mark.parametrize("caminho", [
    f"/v1/connector/consoles/{HOST_ID}/network/api/s/default/cmd/devmgr",
    f"/v1/connector/consoles/{HOST_ID}/network/integration/v1/sites",
    "/v1/hosts",
])
def test_post_recusado_fora_dos_relatorios(caminho):
    c, sessao = cliente()
    with pytest.raises(ErroApi):
        c.consultar_relatorio(caminho, {})
    assert sessao.chamadas == []


def test_nenhum_outro_metodo():
    c, sessao = cliente()
    for metodo in ("PUT", "DELETE", "PATCH"):
        with pytest.raises(ErroApi):
            c._requisitar(metodo, "/v1/hosts")
    assert sessao.chamadas == []
    assert not any(hasattr(c, nome) for nome in ("put", "delete", "patch", "post"))


# Segurança da chamada --------------------------------------------------------

def test_chamada_segura():
    c, sessao = cliente(Resposta(corpo={}))
    c.get("/v1/hosts")
    chamada = sessao.chamadas[0]
    assert chamada["url"] == "https://api.ui.com/v1/hosts"
    assert chamada["verify"] is True
    assert chamada["allow_redirects"] is False
    assert chamada["headers"]["X-API-Key"] == CHAVE
    assert sessao.trust_env is False


def test_nao_segue_redirecionamento():
    c, _ = cliente(Resposta(302, cabecalhos={"Location": "https://outro-site.com/"}))
    with pytest.raises(ErroApi) as erro:
        c.get("/v1/hosts")
    assert erro.value.codigo == "resposta"


def test_chave_nao_aparece_no_repr():
    c, _ = cliente()
    assert CHAVE not in repr(c)
    assert CHAVE not in str(c)


def test_chave_vazia_recusada():
    with pytest.raises(ErroApi):
        ClienteUniFi("")


# Respostas da UniFi ----------------------------------------------------------

@pytest.mark.parametrize("status,codigo", [
    (401, "chave_recusada"),
    (403, "sem_permissao"),
    (404, "resposta"),
])
def test_erros_viram_mensagem_sem_a_chave(status, codigo):
    c, _ = cliente(Resposta(status))
    with pytest.raises(ErroApi) as erro:
        c.get("/v1/hosts")
    assert erro.value.codigo == codigo
    assert CHAVE not in str(erro.value)


def test_429_respeita_retry_after_e_tenta_de_novo(sem_espera):
    c, sessao = cliente(Resposta(429, cabecalhos={"Retry-After": "7"}), Resposta(corpo={"ok": 1}))
    inicio = sem_espera["agora"]
    assert c.get("/v1/hosts") == {"ok": 1}
    assert sem_espera["agora"] - inicio == 7
    assert len(sessao.chamadas) == 2


def test_429_que_estoura_o_prazo_desiste():
    c, sessao = cliente(Resposta(429, cabecalhos={"Retry-After": "40"}), prazo=30)
    with pytest.raises(ErroApi) as erro:
        c.get("/v1/hosts")
    assert erro.value.codigo == "limite"
    assert len(sessao.chamadas) == 1


def test_429_sempre_desiste_depois_das_tentativas():
    c, _ = cliente(*[Resposta(429, cabecalhos={"Retry-After": "1"})] * 3)
    with pytest.raises(ErroApi) as erro:
        c.get("/v1/hosts")
    assert erro.value.codigo == "limite"


def test_erro_500_tenta_de_novo():
    c, sessao = cliente(Resposta(502), Resposta(corpo={"ok": 1}))
    assert c.get("/v1/hosts") == {"ok": 1}
    assert len(sessao.chamadas) == 2


def test_falha_de_rede():
    erro_rede = requests.ConnectionError(f"falhou com {CHAVE}")
    c, _ = cliente(erro_rede, erro_rede, erro_rede)
    with pytest.raises(ErroApi) as erro:
        c.get("/v1/hosts")
    assert erro.value.codigo == "rede"
    assert CHAVE not in str(erro.value)
    assert erro.value.__cause__ is None and erro.value.__suppress_context__


def test_tempo_esgotado():
    c, _ = cliente(*[requests.Timeout()] * 3)
    with pytest.raises(ErroApi) as erro:
        c.get("/v1/hosts")
    assert erro.value.codigo == "tempo"


def test_resposta_que_nao_e_json():
    c, _ = cliente(Resposta(bruto=b"<html>"))
    with pytest.raises(ErroApi) as erro:
        c.get("/v1/hosts")
    assert erro.value.codigo == "resposta"


def test_resposta_grande_demais(monkeypatch):
    monkeypatch.setattr(api, "MAX_BYTES", 100)
    c, _ = cliente(Resposta(bruto=b"[" + b"1," * 100 + b"1]"))
    with pytest.raises(ErroApi) as erro:
        c.get("/v1/hosts")
    assert "grande demais" in str(erro.value)


# Consoles ---------------------------------------------------------------------

HOST_UDR = {
    "id": HOST_ID,
    "type": "console",
    "userData": {"email": "dono@exemplo.com", "fullName": "Fulano"},
    "reportedState": {
        "name": "UDR Lab",
        "state": "connected",
        "version": "4.3.6",
        "hardware": {"name": "UniFi Dream Router", "firmwareVersion": "4.3.6"},
        "controllers": [{"name": "network", "version": "10.5.67"}],
        "location": {"lat": -23.5, "long": -46.6},
    },
}
HOST_ANTIGO = {"id": "antigo:1", "type": "network-server",
               "reportedState": {"hostname": "servidor-velho", "state": "disconnected", "version": "8.0.7"}}


def test_listar_hosts_segue_paginas():
    c, sessao = cliente(
        Resposta(corpo={"data": [HOST_UDR], "nextToken": "pag2"}),
        Resposta(corpo={"data": [HOST_ANTIGO]}),
    )
    hosts = c.listar_hosts()
    assert [h["id"] for h in hosts] == [HOST_ID, "antigo:1"]
    assert sessao.chamadas[1]["params"]["nextToken"] == "pag2"


def test_resumo_guarda_so_o_necessario():
    udr, antigo = resumir_hosts([HOST_UDR, HOST_ANTIGO, {"type": "sem-id"}])
    assert udr == {
        "host_id": HOST_ID, "nome": "UDR Lab", "modelo": "UniFi Dream Router", "tipo": "console",
        "conectado": True, "firmware": "4.3.6", "versao_network": "10.5.67",
    }
    texto = json.dumps(udr)
    assert "dono@exemplo.com" not in texto and "Fulano" not in texto and "-23.5" not in texto
    assert antigo["nome"] == "servidor-velho"
    assert antigo["conectado"] is False
    assert antigo["versao_network"] == "8.0.7"
