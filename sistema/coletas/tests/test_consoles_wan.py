"""Coletas de consoles e WAN, rodando a tarefa inteira com a UniFi simulada."""
from datetime import datetime, timedelta, timezone as tz

import pytest
from django.db import DatabaseError, connection, transaction

from clientes.models import Cliente
from coletas import tarefas as coleta
from coletas.models import ConsoleEstado, ExecucaoColeta, WanHora
from conexoes.models import ChaveUniFi, Console
from organizacoes.isolamento import contexto
from tarefas.fila import executar, pegar_proxima

pytestmark = pytest.mark.django_db

INICIO = datetime(2026, 11, 20, 0, 0, tzinfo=tz.utc)


def host(host_id, nome, conectado=True):
    return {
        "id": host_id, "type": "console",
        "userData": {"email": "dono@exemplo.com", "fullName": "Fulano"},
        "latestBackupTime": "2026-11-20T03:00:00Z",
        "lastConnectionStateChange": "2026-11-01T12:00:00Z",
        "reportedState": {
            "name": nome, "state": "connected" if conectado else "disconnected", "version": "4.3.6",
            "hardware": {"name": "UniFi Dream Router", "firmwareVersion": "4.3.6"},
            "controllers": [{"name": "network", "version": "10.5.67"}],
            "firmwareUpdate": {"latestAvailableVersion": "4.4.1"},
            "wans": [{"plugged": True}, {"plugged": False}],
            "location": {"lat": -23.5, "long": -46.6},
        },
    }


def periodo(hora, perda=0.0, uptime=100):
    return {
        "metricTime": (INICIO + timedelta(hours=hora)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data": {"wan": {"avgLatency": 12, "maxLatency": 40, "packetLoss": perda, "uptime": uptime,
                         "downtime": 0, "download_kbps": 500000, "upload_kbps": 250000,
                         "ispName": "V.tal", "ispAsn": "8167"}},
    }


class UniFiFalsa:
    def __init__(self):
        self.hosts = [host("udr:1", "UDR Lab"), host("outro:2", "Console de outro cliente")]
        self.metricas = [
            {"hostId": "udr:1", "siteId": "site-a", "periods": [periodo(0), periodo(1, perda=2.5), periodo(3)]},
            {"hostId": "outro:2", "siteId": "site-x", "periods": [periodo(0)]},
        ]
        self.chamadas = []

    def listar_hosts(self):
        self.chamadas.append(("hosts", None))
        return list(self.hosts)

    def get(self, caminho, parametros=None):
        self.chamadas.append((caminho, parametros))
        assert caminho == "/v1/isp-metrics/1h"
        return {"data": self.metricas}


@pytest.fixture
def unifi(monkeypatch):
    falsa = UniFiFalsa()
    monkeypatch.setattr(coleta, "criar_cliente_api", lambda texto: falsa)
    return falsa


@pytest.fixture
def cenario(msps, monkeypatch):
    # Só as partes deste arquivo (equipamentos tem testes próprios).
    monkeypatch.setattr(coleta, "_partes", [p for p in coleta._partes if p[1] in ("Consoles", "WAN")])
    for org, cliente, texto in [
        (msps.org_a, msps.cliente_a, "chaveDoClienteA-0123456789-abcd"),
        (msps.org_b, msps.cliente_b, "chaveDoClienteB-0123456789-wxyz"),
    ]:
        with contexto(organizacao_id=org.pk):
            chave = ChaveUniFi(cliente=cliente)
            chave.definir(texto)
            chave.save()
            Console.objects.create(cliente=cliente, host_id="udr:1", nome="UDR Lab", conectado=True, acompanhar=True)
            Console.objects.create(cliente=cliente, host_id="outro:2", nome="Outro", acompanhar=False)
    return msps


def rodar(org, cliente):
    coleta.enfileirar_coleta(org.pk, cliente.pk)
    executar(pegar_proxima())
    with contexto(organizacao_id=org.pk):
        return ExecucaoColeta.objects.filter(cliente=cliente).first()


def wan(org, cliente):
    with contexto(organizacao_id=org.pk):
        return list(WanHora.objects.filter(cliente=cliente).order_by("horario"))


def sql(texto, parametros=None):
    with connection.cursor() as cur:
        cur.execute(texto, parametros or [])
        return cur.fetchall() if cur.description else cur.rowcount


# Consoles --------------------------------------------------------------------------

def test_foto_so_dos_consoles_acompanhados(cenario, unifi):
    execucao = rodar(cenario.org_a, cenario.cliente_a)
    assert execucao.resultado == "ok"
    assert execucao.partes[0] == {"nome": "Consoles", "ok": True, "mensagem": "1 console(s) acompanhado(s), 1 conectado(s)"}
    with contexto(organizacao_id=cenario.org_a.pk):
        (foto,) = ConsoleEstado.objects.select_related("console")
    assert foto.console.host_id == "udr:1"
    assert (foto.firmware, foto.versao_network, foto.atualizacao_disponivel) == ("4.3.6", "10.5.67", "4.4.1")
    assert foto.conectado is True and foto.wans_conectadas == 1
    assert foto.ultimo_backup == datetime(2026, 11, 20, 3, 0, tzinfo=tz.utc)


def test_dados_pessoais_nao_sao_gravados(cenario, unifi):
    rodar(cenario.org_a, cenario.cliente_a)
    with contexto(organizacao_id=cenario.org_a.pk):
        texto = str(list(ConsoleEstado.objects.values())) + str(list(Console.objects.values()))
    assert "dono@exemplo.com" not in texto and "Fulano" not in texto and "-23.5" not in texto


def test_coleta_atualiza_a_lista_de_consoles(cenario, unifi):
    unifi.hosts = [host("udr:1", "UDR renomeado", conectado=False)]
    execucao = rodar(cenario.org_a, cenario.cliente_a)
    with contexto(organizacao_id=cenario.org_a.pk):
        udr = Console.objects.get(cliente=cenario.cliente_a, host_id="udr:1")
        outro = Console.objects.get(cliente=cenario.cliente_a, host_id="outro:2")
    assert udr.nome == "UDR renomeado" and udr.conectado is False
    assert outro.na_conta is False
    assert "0 conectado(s)" in execucao.partes[0]["mensagem"]


# WAN ---------------------------------------------------------------------------------

def test_wan_primeira_coleta_busca_30_dias_e_depois_7(cenario, unifi):
    rodar(cenario.org_a, cenario.cliente_a)
    rodar(cenario.org_a, cenario.cliente_a)
    duracoes = [p["duration"] for c, p in unifi.chamadas if c == "/v1/isp-metrics/1h"]
    assert duracoes == ["30d", "7d"]


def test_wan_grava_so_consoles_acompanhados_e_nao_inventa_hora(cenario, unifi):
    execucao = rodar(cenario.org_a, cenario.cliente_a)
    linhas = wan(cenario.org_a, cenario.cliente_a)
    assert [l.horario.hour for l in linhas] == [0, 1, 3]  # a hora 2 não veio: não existe linha
    assert {l.site_id for l in linhas} == {"site-a"}
    assert linhas[1].perda_pct == 2.5 and linhas[1].provedor == "V.tal" and linhas[1].download_kbps == 500000
    assert execucao.partes[1]["mensagem"] == "3 hora(s) de 1 site(s) (primeira coleta, 30 dias)"


def test_wan_rodar_de_novo_atualiza_sem_duplicar(cenario, unifi):
    rodar(cenario.org_a, cenario.cliente_a)
    unifi.metricas[0]["periods"][1] = periodo(1, perda=7.0)
    unifi.metricas[0]["periods"].append(periodo(2))
    rodar(cenario.org_a, cenario.cliente_a)
    linhas = wan(cenario.org_a, cenario.cliente_a)
    assert [l.horario.hour for l in linhas] == [0, 1, 2, 3]
    assert linhas[1].perda_pct == 7.0


def test_wan_ignora_periodo_com_data_invalida(cenario, unifi):
    unifi.metricas[0]["periods"].append({"metricTime": "ontem", "data": {}})
    unifi.metricas[0]["periods"].append({"data": {}})
    rodar(cenario.org_a, cenario.cliente_a)
    assert len(wan(cenario.org_a, cenario.cliente_a)) == 3


def test_falha_na_wan_nao_derruba_consoles(cenario, unifi):
    from unifi.api import ErroApi

    def falha(caminho, parametros=None):
        raise ErroApi("sem_permissao", "A chave não tem permissão para /v1/isp-metrics/1h (403).")

    unifi.get = falha
    execucao = rodar(cenario.org_a, cenario.cliente_a)
    assert execucao.resultado == "parcial"
    assert [p["ok"] for p in execucao.partes] == [True, False]


# Isolamento ---------------------------------------------------------------------------

def test_mesmo_console_em_duas_organizacoes_fica_separado(cenario, unifi):
    rodar(cenario.org_a, cenario.cliente_a)
    rodar(cenario.org_b, cenario.cliente_b)
    assert len(wan(cenario.org_a, cenario.cliente_a)) == 3
    assert len(wan(cenario.org_b, cenario.cliente_b)) == 3
    for tabela in ("coletas_wanhora", "coletas_consoleestado"):
        with contexto(organizacao_id=cenario.org_a.pk):
            orgs = sql(f"select distinct organizacao_id from {tabela}")
        assert orgs == [(cenario.org_a.pk,)]
        assert sql(f"select count(*) from {tabela}") == [(0,)]  # sem organização
        assert sql(
            "select relrowsecurity, relforcerowsecurity from pg_class where relname = %s", [tabela]
        ) == [(True, True)]


def test_banco_recusa_dado_com_console_de_outro_cliente(cenario):
    with contexto(organizacao_id=cenario.org_a.pk):
        filial = Cliente.objects.create(nome="Filial do A")
        console_a = Console.objects.get(cliente=cenario.cliente_a, host_id="udr:1")
        inserir = (
            "insert into coletas_wanhora (organizacao_id, cliente_id, console_id, coletado_em, site_id, "
            "horario, provedor, asn) values (%s, %s, %s, now(), 's', now(), '', '')"
        )
        with pytest.raises(DatabaseError) as erro, transaction.atomic():
            sql(inserir, [cenario.org_a.pk, filial.pk, console_a.pk])
            sql("set constraints all immediate")
        assert "console_mesmo_cliente" in str(erro.value)
        with transaction.atomic():  # controle: com o cliente certo, funciona
            sql(inserir, [cenario.org_a.pk, cenario.cliente_a.pk, console_a.pk])
            sql("set constraints all immediate")


def test_banco_recusa_console_de_outra_organizacao(cenario):
    with contexto(organizacao_id=cenario.org_b.pk):
        console_b = Console.objects.get(cliente=cenario.cliente_b, host_id="udr:1")
    with contexto(organizacao_id=cenario.org_a.pk):
        with pytest.raises(DatabaseError), transaction.atomic():
            sql(
                "insert into coletas_wanhora (organizacao_id, cliente_id, console_id, coletado_em, site_id, "
                "horario, provedor, asn) values (%s, %s, %s, now(), 's', now(), '', '')",
                [cenario.org_a.pk, cenario.cliente_a.pk, console_b.pk],
            )
            sql("set constraints all immediate")
