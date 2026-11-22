"""Dispositivos conectados, consumo, aplicativos e catálogos, com a UniFi simulada."""
from datetime import datetime, timedelta, timezone as tz

import pytest
from django.db import connection

from coletas import tarefas as coleta
from coletas.coletores import catalogos, clientes, consumo, equipamentos as equip
from coletas.models import (
    AplicativoDia, Catalogo, ClienteAmostra, ClienteDia, ExecucaoColeta, InternetDia, InternetHora,
    NaoIdentificadoDia, SiteNetwork,
)
from conexoes.models import ChaveUniFi, Console
from organizacoes.isolamento import contexto
from tarefas.fila import executar, pegar_proxima
from unifi.api import GET_PERMITIDOS, POST_PERMITIDOS, ErroApi, _conferir

pytestmark = pytest.mark.django_db

MEIA_NOITE_20_SP = datetime(2026, 11, 20, 3, 0, tzinfo=tz.utc)  # 20/11 00:00 em São Paulo
MAC_PESSOA = "11:22:33:44:55:66"


def ms(momento):
    return int(momento.timestamp() * 1000)


class UniFiFalsa:
    def __init__(self):
        self.chamadas = []
        self.falhar = {}
        self.ativos = [
            {"mac": MAC_PESSOA, "display_name": "Celular da Ana", "type": "WIRELESS", "oui": "Apple",
             "model_name": "iPhone", "fingerprint": {"os_name": 24}, "essid": "Casa", "signal": -61,
             "wifi_experience_score": 92, "wifi_tx_retries_percentage": 4.5, "uptime": 3600},
            {"mac": "aa:aa:aa:aa:aa:aa", "hostname": "pc", "is_wired": True, "sw_port": 3, "wired_rate_mbps": 1000,
             "signal": -10},
        ]

    def _registrar(self, caminho, permitidos):
        _conferir(caminho, permitidos)
        self.chamadas.append(caminho)
        for sufixo, erro in self.falhar.items():
            if caminho.endswith(sufixo):
                raise erro

    def get(self, caminho, parametros=None):
        self._registrar(caminho, GET_PERMITIDOS)
        if caminho.endswith("/clients/active"):
            return self.ativos
        if caminho.endswith("/traffic"):
            return {
                "total_usage_by_app": [
                    {"category": 13, "application": 94, "bytes_received": 5000, "bytes_transmitted": 700,
                     "client_count": 2},
                    {"category": 255, "application": 65535, "bytes_received": 300, "bytes_transmitted": 30,
                     "client_count": 1},
                ],
                "client_usage_by_app": [
                    {"client": {"mac": MAC_PESSOA, "fingerprint": {"dev_family": 9}},
                     "usage_by_app": [{"application": 65535, "total_bytes": 330}, {"application": 94, "total_bytes": 10}]},
                    {"client": {"mac": "bb:bb", "fingerprint": {}},
                     "usage_by_app": [{"application": 65535, "total_bytes": 70}]},
                ],
            }
        if caminho.endswith("/dpi/categories"):
            return {"data": [{"id": 13, "name": "Streaming"}], "totalCount": 1}
        if caminho.endswith("/dpi/applications"):
            return {"data": [{"id": 94, "name": "YouTube"}, {"id": "x", "name": "inválido"}], "totalCount": 2}
        if caminho.endswith("/fingerprint_devices/0"):
            return {"os_name_ids": {"24": "iOS"}, "family_ids": {"9": "Smartphone"}, "email": "nao@guardar"}
        raise AssertionError(caminho)

    def consultar_relatorio(self, caminho, corpo):
        self._registrar(caminho, POST_PERMITIDOS)
        if caminho.endswith("daily.site"):
            return {"data": [{"time": ms(MEIA_NOITE_20_SP), "wan-rx_bytes": 9_000_000, "wan-tx_bytes": 1_000_000,
                              "num_sta": 12}]}
        if caminho.endswith("daily.user"):
            return {"data": [{"time": ms(MEIA_NOITE_20_SP), "user": MAC_PESSOA, "tx_bytes": 800, "rx_bytes": 90}]}
        return {"data": [{"time": ms(MEIA_NOITE_20_SP + timedelta(hours=20)), "wan-rx_bytes": 50, "wan-tx_bytes": 5,
                          "num_sta": 4}]}


@pytest.fixture
def unifi(monkeypatch):
    falsa = UniFiFalsa()
    monkeypatch.setattr(coleta, "criar_cliente_api", lambda texto: falsa)
    monkeypatch.setattr(equip.time, "sleep", lambda s: None)
    return falsa


@pytest.fixture
def cenario(msps):
    with contexto(organizacao_id=msps.org_a.pk):
        chave = ChaveUniFi(cliente=msps.cliente_a)
        chave.definir("chaveDoClienteA-0123456789-abcd")
        chave.save()
        msps.udr = Console.objects.create(cliente=msps.cliente_a, host_id="udr:1", nome="UDR", tipo="console",
                                          conectado=True, acompanhar=True)
        SiteNetwork.objects.create(cliente=msps.cliente_a, console=msps.udr, site_id="uuid", referencia="default")
    return msps


def so_partes(monkeypatch, *funcoes):
    monkeypatch.setattr(coleta, "_partes", [(i, f.__module__, f) for i, f in enumerate(funcoes)])


def rodar(msps, agora=None, forcar=False, monkeypatch=None):
    if agora and monkeypatch:
        monkeypatch.setattr(coleta.timezone, "now", lambda: agora)
    coleta.enfileirar_coleta(msps.org_a.pk, msps.cliente_a.pk, forcar=forcar)
    executar(pegar_proxima())
    with contexto(organizacao_id=msps.org_a.pk):
        return ExecucaoColeta.objects.order_by("-pk").first()


def linhas(msps, modelo):
    with contexto(organizacao_id=msps.org_a.pk):
        return list(modelo.objects.all())


# Dispositivos conectados ---------------------------------------------------------

def test_dispositivos_conectados(cenario, unifi, monkeypatch):
    so_partes(monkeypatch, clientes.coletar)
    execucao = rodar(cenario)
    assert execucao.partes[0]["mensagem"] == "2 dispositivo(s) conectado(s)"
    assert any(c.endswith("/v2/api/site/default/clients/active") for c in unifi.chamadas)
    por_mac = {a.mac: a for a in linhas(cenario, ClienteAmostra)}
    ana = por_mac[MAC_PESSOA]
    assert (ana.nome, ana.fabricante, ana.so_id, ana.ssid, ana.sinal_dbm, ana.experiencia) == (
        "Celular da Ana", "Apple", 24, "Casa", -61, 92)
    pc = por_mac["aa:aa:aa:aa:aa:aa"]
    assert pc.tipo == "WIRED" and pc.sinal_dbm is None and pc.velocidade_mbps == 1000


def test_sem_site_conhecido_usa_default(cenario, unifi, monkeypatch):
    with contexto(organizacao_id=cenario.org_a.pk):
        SiteNetwork.objects.all().delete()
    so_partes(monkeypatch, clientes.coletar)
    rodar(cenario)
    assert any("/site/default/clients/active" in c for c in unifi.chamadas)


# Consumo e aplicativos -------------------------------------------------------------

def test_consumo_primeira_vez(cenario, unifi, monkeypatch):
    so_partes(monkeypatch, consumo.coletar)
    agora = datetime(2026, 11, 21, 15, 0, tzinfo=tz.utc)
    execucao = rodar(cenario, agora, monkeypatch=monkeypatch)
    assert execucao.resultado == "ok", execucao.partes
    # O console só guarda aplicativos do dia corrente: 1 chamada, só hoje.
    assert sum(1 for c in unifi.chamadas if c.endswith("/traffic")) == 1
    assert execucao.partes[0]["mensagem"] == (
        "UDR/default: 1 dia(s) de internet, 1 registro(s) de dispositivos, 2 aplicativo(s) hoje")

    (dia,) = linhas(cenario, InternetDia)
    assert dia.dia.isoformat() == "2026-11-20"           # dia no horário de Brasília
    assert (dia.download_bytes, dia.upload_bytes, dia.clientes) == (9_000_000, 1_000_000, 12)
    (disp,) = linhas(cenario, ClienteDia)
    assert (disp.download_bytes, disp.upload_bytes) == (800, 90)   # tx = download nos dispositivos
    (hora,) = linhas(cenario, InternetHora)
    assert hora.hora == MEIA_NOITE_20_SP + timedelta(hours=20)

    apps = linhas(cenario, AplicativoDia)
    assert {(a.categoria_id, a.aplicativo_id) for a in apps} == {(13, 94), (255, 65535)}
    assert {a.dia.isoformat() for a in apps} == {"2026-11-21"}
    nao_ident = {(n.familia_id, n.bytes, n.dispositivos) for n in linhas(cenario, NaoIdentificadoDia)}
    assert nao_ident == {(9, 330, 1), (-1, 70, 1)}


def test_aplicativo_por_pessoa_nunca_e_gravado(cenario, unifi, monkeypatch):
    so_partes(monkeypatch, consumo.coletar)
    rodar(cenario)
    with contexto(organizacao_id=cenario.org_a.pk):
        texto = str(list(AplicativoDia.objects.values())) + str(list(NaoIdentificadoDia.objects.values()))
    assert MAC_PESSOA not in texto and "bb:bb" not in texto


def test_relatorios_a_cada_6_horas_e_aplicativos_em_toda_coleta(cenario, unifi, monkeypatch):
    so_partes(monkeypatch, consumo.coletar)
    agora = datetime(2026, 11, 21, 15, 0, tzinfo=tz.utc)
    rodar(cenario, agora, monkeypatch=monkeypatch)
    unifi.chamadas.clear()
    execucao = rodar(cenario, agora + timedelta(hours=2), monkeypatch=monkeypatch)
    assert execucao.partes[0]["mensagem"] == "UDR/default: 2 aplicativo(s) hoje"
    assert [c.rsplit("/", 1)[-1] for c in unifi.chamadas] == ["traffic"]
    unifi.chamadas.clear()
    rodar(cenario, agora + timedelta(hours=6), monkeypatch=monkeypatch)
    assert sum(1 for c in unifi.chamadas if "stat/report" in c) == 3


def test_forcar_refaz_os_relatorios_sem_duplicar(cenario, unifi, monkeypatch):
    so_partes(monkeypatch, consumo.coletar)
    agora = datetime(2026, 11, 21, 15, 0, tzinfo=tz.utc)
    rodar(cenario, agora, monkeypatch=monkeypatch)
    antes = len(linhas(cenario, AplicativoDia))
    unifi.chamadas.clear()
    rodar(cenario, agora + timedelta(hours=1), forcar=True, monkeypatch=monkeypatch)
    assert sum(1 for c in unifi.chamadas if "stat/report" in c) == 3
    assert len(linhas(cenario, AplicativoDia)) == antes
    assert len(linhas(cenario, InternetDia)) == 1


def test_sem_relatorio_por_hora_segue_sem_ele(cenario, unifi, monkeypatch):
    so_partes(monkeypatch, consumo.coletar)
    unifi.falhar["hourly.site"] = ErroApi("resposta", "Erro 404 ao chamar ...")
    execucao = rodar(cenario)
    assert execucao.resultado == "ok"
    assert linhas(cenario, InternetHora) == [] and len(linhas(cenario, InternetDia)) == 1


def test_falha_no_relatorio_diario_falha_a_parte(cenario, unifi, monkeypatch):
    so_partes(monkeypatch, consumo.coletar)
    unifi.falhar["daily.site"] = ErroApi("servidor", "A UniFi está com problema (erro 502).")
    execucao = rodar(cenario)
    assert execucao.resultado == "falhou"
    assert linhas(cenario, InternetDia) == []


# Catálogos -------------------------------------------------------------------------

def test_catalogos_uma_vez_por_semana_para_a_plataforma(cenario, unifi, monkeypatch):
    so_partes(monkeypatch, catalogos.coletar)
    agora = datetime(2026, 11, 21, 15, 0, tzinfo=tz.utc)
    execucao = rodar(cenario, agora, monkeypatch=monkeypatch)
    assert execucao.partes[0]["mensagem"].startswith("1 categoria(s) e 2 aplicativo(s)")
    # Tabela da plataforma: lida sem organização.
    nomes = dict(((c.tipo, c.id_unifi), c.nome) for c in Catalogo.objects.all())
    assert nomes == {("dpi_categoria", 13): "Streaming", ("dpi_aplicativo", 94): "YouTube",
                     ("so", 24): "iOS", ("familia", 9): "Smartphone"}
    assert "nao@guardar" not in str(list(Catalogo.objects.values()))
    execucao = rodar(cenario, agora + timedelta(days=3), monkeypatch=monkeypatch)
    assert execucao.partes[0]["mensagem"] == "em dia (atualiza 1x por semana)"


# Isolamento ------------------------------------------------------------------------

@pytest.mark.parametrize("tabela", [
    "coletas_clienteamostra", "coletas_internetdia", "coletas_internethora", "coletas_clientedia",
    "coletas_aplicativodia", "coletas_naoidentificadodia", "coletas_controlecoleta",
])
def test_rls_ligada_e_isolada(cenario, unifi, monkeypatch, tabela):
    so_partes(monkeypatch, clientes.coletar, consumo.coletar)
    rodar(cenario)
    with connection.cursor() as cur:
        cur.execute("select relrowsecurity, relforcerowsecurity from pg_class where relname = %s", [tabela])
        assert cur.fetchone() == (True, True)
        cur.execute(f"select count(*) from {tabela}")
        assert cur.fetchone() == (0,)
    with contexto(organizacao_id=cenario.org_a.pk), connection.cursor() as cur:
        cur.execute(f"select count(*) from {tabela}")
        assert cur.fetchone()[0] > 0
    with contexto(organizacao_id=cenario.org_b.pk), connection.cursor() as cur:
        cur.execute(f"select count(*) from {tabela}")
        assert cur.fetchone() == (0,)
