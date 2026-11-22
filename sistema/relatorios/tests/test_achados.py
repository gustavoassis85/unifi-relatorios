"""Pontos de atenção portados do MVP, incidentes e higiene da conta (dados montados no teste)."""
from datetime import date, datetime, timedelta, timezone as tz

import pytest

from coletas import models as m
from conexoes.models import Console
from organizacoes.isolamento import contexto
from relatorios import achados as regras
from relatorios.achados import avaliar
from relatorios.fonte import Fonte

pytestmark = pytest.mark.django_db

INICIO = datetime(2026, 11, 1, 3, 0, tzinfo=tz.utc)   # 01/11 00h em Brasília
FIM = INICIO + timedelta(days=10)


@pytest.fixture
def lab(msps):
    with contexto(organizacao_id=msps.org_a.pk):
        msps.udr = Console.objects.create(cliente=msps.cliente_a, host_id="udr:1", nome="UDR", tipo="console",
                                          conectado=True, acompanhar=True)
    return msps


def criar(lab, tabela, /, console=None, **campos):
    with contexto(organizacao_id=lab.org_a.pk):
        return tabela.objects.create(cliente=lab.cliente_a, console=console or lab.udr, **campos)


def horas_wan(lab, dia, perdas=None, faltando=(), latencia=10.0):
    """24 horas de WAN no dia (n = dia do período), com perda por hora e horas que faltam."""
    for h in range(24):
        if h in faltando:
            continue
        perda = perdas(h) if callable(perdas) else (perdas or 0.0)
        criar(lab, m.WanHora, site_id="s", horario=INICIO + timedelta(days=dia, hours=h), perda_pct=perda,
              latencia_media=latencia, latencia_max=latencia * 2, provedor="V.tal")


def rodar(lab, consoles_da_conta=()):
    with contexto(organizacao_id=lab.org_a.pk):
        acompanhados = Console.objects.filter(cliente=lab.cliente_a, acompanhar=True)
        return avaliar(Fonte(lab.cliente_a, acompanhados), INICIO, FIM, consoles_da_conta)


def titulos(achados):
    return [(a.severidade, a.titulo) for a in achados]


# Link -------------------------------------------------------------------------------

def test_link_sem_dados(lab):
    horas_wan(lab, 0, faltando=range(5, 10))
    horas_wan(lab, 1)
    achados, _, erros = rodar(lab)
    assert erros == []
    (a,) = achados
    assert (a.severidade, a.titulo) == ("alta", "Link sem dados por 5 horas")
    assert "01/11 das 05h às 10h (5h)" in a.evidencia


def test_hora_ausente_nunca_conta_como_link_ok(lab):
    horas_wan(lab, 0, faltando=[12])
    (a,), _, _ = rodar(lab)
    assert a.titulo == "Link sem dados por 1 hora" and a.severidade == "media"


def test_perda_em_episodio(lab):
    horas_wan(lab, 0)
    horas_wan(lab, 1, perdas=3.0)
    horas_wan(lab, 2, perdas=lambda h: 25.0 if h == 9 else 2.0)
    horas_wan(lab, 3)
    (a,), _, _ = rodar(lab)
    assert (a.severidade, a.titulo) == ("alta", "Perda de pacote acima do normal no link V.tal")
    assert "02/11 a 03/11" in a.evidencia and "pico de 25% em 03/11 09h" in a.evidencia


def test_picos_isolados(lab):
    horas_wan(lab, 0, perdas=lambda h: 15.0 if h == 3 else 0.0)
    (a,), _, _ = rodar(lab)
    assert (a.severidade, a.titulo) == ("baixa", "Picos isolados de perda de pacote no link V.tal")


def test_latencia_alta(lab):
    horas_wan(lab, 0, latencia=120.0)
    (a,), _, _ = rodar(lab)
    assert (a.severidade, a.titulo) == ("alta", "Latência alta no link V.tal")


def test_queda_e_perda_no_mesmo_dia_viram_um_incidente(lab):
    horas_wan(lab, 0, perdas=4.0, faltando=range(2, 8))
    horas_wan(lab, 1)
    achados, _, _ = rodar(lab)
    assert titulos(achados) == [("alta", "Quedas e perda de pacote no link V.tal")]
    assert "6 horas sem nenhuma métrica" in achados[0].evidencia and "instabilidade" in achados[0].evidencia


def test_queda_e_perda_em_dias_diferentes_ficam_separadas(lab):
    horas_wan(lab, 0, faltando=range(2, 8))
    horas_wan(lab, 1)
    horas_wan(lab, 2, perdas=4.0)
    horas_wan(lab, 3)
    achados, _, _ = rodar(lab)
    assert {a.tipo for a in achados} == {"wan_sem_dado", "wan_perda"}


# Consoles ---------------------------------------------------------------------------

def foto(lab, quando, **campos):
    base = {"nome": "UDR", "modelo": "UniFi Dream Router", "tipo": "console", "conectado": True,
            "firmware": "5.1.19", "ultimo_backup": quando - timedelta(days=1)}
    criar(lab, m.ConsoleEstado, coletado_em=quando, **{**base, **campos})


def test_console_offline(lab):
    foto(lab, FIM - timedelta(hours=1), conectado=False, mudou_estado_em=FIM - timedelta(days=3))
    achados, _, _ = rodar(lab)
    assert ("alta", "Console sem conexão com a nuvem") in titulos(achados)


def test_backup_desatualizado_e_atualizacao_pendente(lab):
    foto(lab, FIM - timedelta(days=2), atualizacao_disponivel="6.0.17+abc")
    foto(lab, FIM - timedelta(hours=1), ultimo_backup=FIM - timedelta(days=40), atualizacao_disponivel="6.0.17+abc")
    achados, _, _ = rodar(lab)
    assert ("alta", "Backup em nuvem desatualizado") in titulos(achados)
    atualizacao = next(a for a in achados if a.tipo == "atualizacao_console")
    assert "a versão 6.0.17 está disponível" in atualizacao.evidencia


def test_disponibilidade_do_console(lab):
    for h in range(30):
        foto(lab, INICIO + timedelta(hours=h), conectado=h not in (3, 4))
    achados, _, _ = rodar(lab)
    assert ("alta", "Console com quedas de conexão no período") in titulos(achados)  # 28 de 30 = 93,3%


def test_registro_antigo_vai_para_a_higiene_e_nao_para_o_relatorio(lab):
    foto(lab, FIM - timedelta(hours=1), tipo="network-server", conectado=False, versao_network="8.0.7",
         mudou_estado_em=FIM - timedelta(days=200))
    achados, higiene, _ = rodar(lab)
    assert achados == []
    assert [a.titulo for a in higiene] == ["Registro antigo de controlador na conta"]


def test_console_fora_do_acompanhamento_vai_para_a_higiene(lab):
    with contexto(organizacao_id=lab.org_a.pk):
        velho = Console.objects.create(cliente=lab.cliente_a, host_id="velho:2", nome="CGU antigo",
                                       modelo="UCG Ultra", conectado=False, acompanhar=False)
        conta = [lab.udr, velho]
    _, higiene, _ = rodar(lab, conta)
    assert [a.titulo for a in higiene] == ["CGU antigo fora do acompanhamento"]


# Equipamentos -------------------------------------------------------------------------

def amostra(lab, h, **campos):
    base = {"site_id": "s", "device_id": "ap1", "nome": "AP Sala", "modelo": "U6 Lite", "estado": "ONLINE",
            "uptime_seg": 100_000 + h * 3600, "cpu_pct": 10.0, "memoria_pct": 40.0, "firmware": "6.6.77",
            "firmware_atualizavel": False}
    criar(lab, m.EquipamentoAmostra, coletado_em=INICIO + timedelta(hours=h), **{**base, **campos})


def test_equipamento_offline_reinicio_carga_e_firmware(lab):
    for h in range(30):
        amostra(lab, h, estado="OFFLINE" if h in (5, 6) else "ONLINE", uptime_seg=600 if h == 20 else 100_000 + h * 3600,
                cpu_pct=95.0, memoria_pct=93.0, firmware_atualizavel=(h == 29))
    achados = {a.tipo for a in rodar(lab)[0]}
    assert {"equipamento_offline", "reinicio", "cpu", "memoria", "firmware"} <= achados


def porta(lab, h, velocidade):
    criar(lab, m.PortaEstado, coletado_em=FIM - timedelta(hours=h), device_id="ap1", idx=1, estado="UP",
          velocidade_mbps=velocidade, velocidade_max_mbps=1000)


def test_porta_com_uma_amostra_so_nao_vira_achado(lab):
    amostra(lab, 0)
    porta(lab, 1, 100)
    assert rodar(lab)[0] == []


def test_porta_abaixo_da_capacidade_em_varias_amostras(lab):
    amostra(lab, 0)
    for h in (1, 2, 3):
        porta(lab, h, 100)
    (a,), _, _ = rodar(lab)
    assert a.titulo == "Porta 1 de AP Sala abaixo da capacidade"


def test_radios(lab):
    amostra(lab, 0)
    for h in range(6):
        criar(lab, m.RadioAmostra, coletado_em=INICIO + timedelta(hours=h), device_id="ap1", posicao=0,
              frequencia_ghz=5.0, retransmissao_pct=15.0)
    criar(lab, m.RadioConfig, coletado_em=INICIO, device_id="ap1", posicao=0, frequencia_ghz=2.4, largura_mhz=40, canal=6)
    criar(lab, m.RadioConfig, coletado_em=INICIO, device_id="ap1", posicao=1, frequencia_ghz=5.0, canal=None)
    tipos = {a.tipo for a in rodar(lab)[0]}
    assert tipos == {"retransmissao", "canal_largo", "radio_sem_canal"}


# Dispositivos ---------------------------------------------------------------------------

def test_sinal_wifi_fraco(lab):
    for h in range(6):
        criar(lab, m.ClienteAmostra, coletado_em=INICIO + timedelta(hours=h), site="default", mac="aa", nome="Notebook",
              tipo="WIRELESS", ssid="Casa", sinal_dbm=-82)
    (a,), _, _ = rodar(lab)
    assert (a.severidade, a.titulo) == ("media", "1 dispositivo com sinal Wi-Fi fraco")


def test_dispositivo_que_concentra_o_upload(lab):
    criar(lab, m.InternetDia, site="default", dia=date(2026, 11, 2), upload_bytes=3_000_000_000)
    criar(lab, m.ClienteDia, site="default", mac="bb", dia=date(2026, 11, 2), upload_bytes=2_500_000_000,
          download_bytes=100)
    criar(lab, m.ClienteAmostra, site="default", mac="bb", nome="Servidor", coletado_em=INICIO)
    (a,), _, _ = rodar(lab)
    assert a.titulo == "Servidor concentra o upload da rede"


# Isolamento e robustez -------------------------------------------------------------------

def test_console_nao_acompanhado_nao_entra(lab):
    with contexto(organizacao_id=lab.org_a.pk):
        outro = Console.objects.create(cliente=lab.cliente_a, host_id="outro:3", acompanhar=False)
    criar(lab, m.WanHora, console=outro, site_id="s", horario=INICIO, perda_pct=50.0)
    criar(lab, m.WanHora, console=outro, site_id="s", horario=INICIO + timedelta(hours=5), perda_pct=50.0)
    assert rodar(lab)[0] == []


def test_dados_de_outra_organizacao_nao_entram(lab):
    with contexto(organizacao_id=lab.org_b.pk):
        udr_b = Console.objects.create(cliente=lab.cliente_b, host_id="udr:1", acompanhar=True)
        for h in (0, 9):
            m.WanHora.objects.create(cliente=lab.cliente_b, console=udr_b, site_id="s",
                                     horario=INICIO + timedelta(hours=h), perda_pct=50.0)
    horas_wan(lab, 0)
    assert rodar(lab)[0] == []


def test_regra_com_erro_nao_derruba_as_outras(lab, monkeypatch):
    def quebra(fonte, inicio, fim):
        raise ValueError("detalhe")

    monkeypatch.setattr(regras, "REGRAS", [quebra, regras.regra_wan_latencia])
    horas_wan(lab, 0, latencia=120.0)
    achados, _, erros = rodar(lab)
    assert len(achados) == 1 and erros == ["quebra: ValueError"]


def test_sem_dados_no_periodo(lab):
    assert rodar(lab) == ([], [], [])
