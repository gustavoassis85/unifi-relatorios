"""Coleta de equipamentos (connector) com a UniFi simulada."""
import pytest
from django.db import connection

from coletas import tarefas as coleta
from coletas.coletores import equipamentos as equip
from coletas.models import (
    ClientesAmostra, EquipamentoAmostra, ExecucaoColeta, PortaEstado, RadioAmostra, RadioConfig, SiteNetwork,
)
from conexoes.models import ChaveUniFi, Console
from organizacoes.isolamento import contexto
from tarefas.fila import executar, pegar_proxima
from unifi.api import GET_PERMITIDOS, ErroApi, _conferir

pytestmark = pytest.mark.django_db

SITE = "88f7af54-98f8-306a-a1c7-c9349722b1f6"


def base(host_id):
    return f"/v1/connector/consoles/{host_id}/network/integration/v1"


class UniFiFalsa:
    """Responde como o connector. Passa pela mesma lista de caminhos da peça real."""

    def __init__(self):
        self.chamadas = []
        self.falhar = {}      # caminho (sufixo) -> ErroApi
        self.equipamentos = [
            {"id": "ap1", "name": "AP Sala", "model": "U6 Lite", "macAddress": "aa:bb", "ipAddress": "10.0.0.2",
             "state": "ONLINE", "firmwareVersion": "6.6.77", "firmwareUpdatable": False},
            {"id": "sw1", "name": "Switch", "model": "USW Lite 8", "state": "OFFLINE", "firmwareVersion": "7.1.26"},
        ]
        self.clientes = [{"type": "WIRED"}] * 3 + [{"type": "WIRELESS"}] * 150

    def listar_hosts(self):
        return []

    def get(self, caminho, parametros=None):
        _conferir(caminho, GET_PERMITIDOS)
        self.chamadas.append(caminho)
        for sufixo, erro in self.falhar.items():
            if caminho.endswith(sufixo):
                raise erro
        parametros = parametros or {}
        if caminho.endswith("/sites"):
            return self._pagina([{"id": SITE, "name": "Default", "internalReference": "default"}], parametros)
        if caminho.endswith("/clients"):
            return self._pagina(self.clientes, parametros)
        if caminho.endswith("/devices"):
            return self._pagina(self.equipamentos, parametros)
        if caminho.endswith("/statistics/latest"):
            return {"uptimeSec": 86400, "cpuUtilizationPct": 12.5, "memoryUtilizationPct": 40,
                    "loadAverage1Min": 0.3, "uplink": {"txRateBps": 1000, "rxRateBps": 2000},
                    "interfaces": {"radios": [{"frequencyGHz": 2.4, "txRetriesPct": 8.1},
                                              {"frequencyGHz": 5, "txRetriesPct": 3.2}]}}
        return {"configurationId": "cfg1", "provisionedAt": "2026-11-01T10:00:00Z",
                "interfaces": {"ports": [{"idx": 1, "state": "UP", "connector": "RJ45", "speedMbps": 100,
                                          "maxSpeedMbps": 1000, "poe": {"standard": "802.3af", "enabled": True,
                                                                        "state": "UP"}},
                                         {"idx": 2, "state": "DOWN", "speedMbps": 0, "maxSpeedMbps": 1000}],
                               "radios": [{"frequencyGHz": 2.4, "wlanStandard": "802.11ax", "channelWidthMHz": 20,
                                           "channel": 6}]}}

    @staticmethod
    def _pagina(itens, parametros):
        inicio = parametros.get("offset", 0)
        fim = inicio + parametros.get("limit", 25)
        return {"data": itens[inicio:fim], "totalCount": len(itens)}


@pytest.fixture
def unifi(monkeypatch):
    falsa = UniFiFalsa()
    monkeypatch.setattr(coleta, "criar_cliente_api", lambda texto: falsa)
    return falsa


@pytest.fixture
def relogio(monkeypatch):
    """Relógio falso: registra as esperas do Ritmo sem dormir."""
    estado = {"agora": 0.0, "esperas": []}

    def dormir(segundos):
        estado["esperas"].append(segundos)
        estado["agora"] += segundos

    monkeypatch.setattr(equip.time, "monotonic", lambda: estado["agora"])
    monkeypatch.setattr(equip.time, "sleep", dormir)
    return estado


@pytest.fixture
def cenario(msps, monkeypatch):
    # Só a parte de equipamentos (as outras têm testes próprios).
    monkeypatch.setattr(coleta, "_partes", [(30, "Equipamentos", equip.coletar)])
    with contexto(organizacao_id=msps.org_a.pk):
        chave = ChaveUniFi(cliente=msps.cliente_a)
        chave.definir("chaveDoClienteA-0123456789-abcd")
        chave.save()
        msps.udr = Console.objects.create(cliente=msps.cliente_a, host_id="udr:1", nome="UDR", tipo="console",
                                          conectado=True, acompanhar=True)
    return msps


def rodar(msps):
    coleta.enfileirar_coleta(msps.org_a.pk, msps.cliente_a.pk)
    executar(pegar_proxima())
    with contexto(organizacao_id=msps.org_a.pk):
        return ExecucaoColeta.objects.first()


def linhas(msps, modelo):
    with contexto(organizacao_id=msps.org_a.pk):
        return list(modelo.objects.all())


def test_coleta_completa(cenario, unifi, relogio):
    execucao = rodar(cenario)
    assert execucao.resultado == "ok"
    assert execucao.partes[0]["mensagem"] == (
        "1 console(s), 1 site(s), 2 equipamento(s), 153 cliente(s) conectado(s), 7 chamada(s)"
    )
    (site,) = linhas(cenario, SiteNetwork)
    assert (site.site_id, site.referencia) == (SITE, "default")
    (amostra,) = linhas(cenario, ClientesAmostra)
    assert (amostra.total, amostra.cabo, amostra.wifi) == (153, 3, 150)

    aps = {e.device_id: e for e in linhas(cenario, EquipamentoAmostra)}
    assert aps["ap1"].cpu_pct == 12.5 and aps["ap1"].uptime_seg == 86400 and aps["ap1"].configuracao_id == "cfg1"
    assert aps["sw1"].cpu_pct is None and aps["sw1"].estado == "OFFLINE"  # offline: sem estatísticas
    assert sorted(r.retransmissao_pct for r in linhas(cenario, RadioAmostra)) == [3.2, 8.1]
    portas = {(p.device_id, p.idx): p for p in linhas(cenario, PortaEstado)}
    assert portas[("ap1", 1)].velocidade_mbps == 100 and portas[("ap1", 1)].poe_ativo is True
    assert portas[("ap1", 2)].poe_ativo is None
    assert {(r.device_id, r.canal) for r in linhas(cenario, RadioConfig)} == {("ap1", 6), ("sw1", 6)}


def test_offline_nao_chama_estatisticas(cenario, unifi, relogio):
    rodar(cenario)
    assert not any(c.endswith("sw1/statistics/latest") for c in unifi.chamadas)


def test_ritmo_espaca_as_chamadas_do_console(cenario, unifi, relogio):
    rodar(cenario)
    assert len(relogio["esperas"]) == len(unifi.chamadas) - 1
    assert all(abs(e - equip.INTERVALO_ENTRE_CHAMADAS) < 1e-9 for e in relogio["esperas"])


def test_paginacao(cenario, unifi, relogio):
    rodar(cenario)
    assert sum(1 for c in unifi.chamadas if c.endswith("/clients")) == 2  # 153 clientes, páginas de 100


def test_falha_em_um_equipamento_nao_derruba_os_outros(cenario, unifi, relogio):
    unifi.falhar["ap1/statistics/latest"] = ErroApi("servidor", "A UniFi está com problema (erro 502).")
    execucao = rodar(cenario)
    assert execucao.resultado == "ok"
    assert "1 chamada(s) de equipamento falharam" in execucao.partes[0]["mensagem"]
    assert len(linhas(cenario, EquipamentoAmostra)) == 2


def test_id_malicioso_vindo_da_api_nao_vira_chamada(cenario, unifi, relogio):
    unifi.equipamentos.append({"id": "../../../api/s/default/cmd/devmgr", "state": "ONLINE"})
    rodar(cenario)
    assert not any("cmd" in c for c in unifi.chamadas)


def test_um_console_sem_resposta_nao_derruba_o_outro(cenario, unifi, relogio):
    with contexto(organizacao_id=cenario.org_a.pk):
        Console.objects.create(cliente=cenario.cliente_a, host_id="filial:2", nome="Filial", tipo="console",
                               conectado=True, acompanhar=True)
    unifi.falhar["filial:2/network/integration/v1/sites"] = ErroApi("tempo", "A UniFi demorou demais para responder.")
    execucao = rodar(cenario)
    assert execucao.resultado == "ok"
    assert "sem resposta: Filial (A UniFi demorou demais para responder.)" in execucao.partes[0]["mensagem"]
    assert len(linhas(cenario, SiteNetwork)) == 1


def test_todos_sem_resposta_falha_a_parte(cenario, unifi, relogio):
    unifi.falhar["/sites"] = ErroApi("tempo", "A UniFi demorou demais para responder.")
    execucao = rodar(cenario)
    assert execucao.resultado == "falhou"
    assert execucao.partes[0]["mensagem"].startswith("Nenhum console respondeu")


@pytest.mark.parametrize("campos", [
    {"tipo": "network-server"},
    {"conectado": False},
    {"na_conta": False},
])
def test_consoles_que_nao_entram(cenario, unifi, relogio, campos):
    with contexto(organizacao_id=cenario.org_a.pk):
        Console.objects.filter(pk=cenario.udr.pk).update(**campos)
    execucao = rodar(cenario)
    assert execucao.partes[0]["mensagem"] == "nenhum console conectado"
    assert unifi.chamadas == []


def test_rodar_de_novo_atualiza_o_site_e_soma_amostras(cenario, unifi, relogio):
    rodar(cenario)
    rodar(cenario)
    assert len(linhas(cenario, SiteNetwork)) == 1
    assert len(linhas(cenario, EquipamentoAmostra)) == 4


@pytest.mark.parametrize("tabela", [
    "coletas_sitenetwork", "coletas_clientesamostra", "coletas_equipamentoamostra",
    "coletas_radioamostra", "coletas_radioconfig", "coletas_portaestado",
])
def test_rls_ligada_e_isolada(cenario, unifi, relogio, tabela):
    rodar(cenario)
    with connection.cursor() as cur:
        cur.execute("select relrowsecurity, relforcerowsecurity from pg_class where relname = %s", [tabela])
        assert cur.fetchone() == (True, True)
        cur.execute(f"select count(*) from {tabela}")
        assert cur.fetchone() == (0,)  # sem organização
    with contexto(organizacao_id=cenario.org_b.pk), connection.cursor() as cur:
        cur.execute(f"select count(*) from {tabela}")
        assert cur.fetchone() == (0,)  # outra organização
