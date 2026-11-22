"""Página do cliente (coletas), "Coletar agora", retenção, resumo_cliente e nomes do catálogo."""
from datetime import datetime, timedelta, timezone as tz
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.urls import reverse
from django.utils import timezone

from auditoria.models import Acao, EventoOrganizacao

from coletas import retencao
from coletas.catalogo import Nomes
from coletas.models import (
    Catalogo, ClienteDia, ConsoleEstado, EquipamentoAmostra, ExecucaoColeta, InternetDia, WanHora,
)
from coletas.tarefas import TIPO
from conexoes.models import ChaveUniFi, Console
from organizacoes.isolamento import contexto
from tarefas.models import Situacao, Tarefa
from tarefas.periodicas import nomes as periodicas

pytestmark = pytest.mark.django_db


def preparar(org, cliente, host_id="udr:1"):
    with contexto(organizacao_id=org.pk):
        chave = ChaveUniFi(cliente=cliente)
        chave.definir("chaveDeTeste-0123456789-" + host_id[:4])
        chave.save()
        return Console.objects.create(cliente=cliente, host_id=host_id, nome="UDR Lab", conectado=True, acompanhar=True)


@pytest.fixture
def cenario(msps):
    msps.udr = preparar(msps.org_a, msps.cliente_a)
    msps.udr_b = preparar(msps.org_b, msps.cliente_b)
    return msps


def detalhe(client, cliente):
    return client.get(reverse("clientes:detalhe", args=[cliente.pk])).content.decode()


def coletar(client, cliente):
    return client.post(reverse("coletas:coletar_agora", args=[cliente.pk]), follow=True)


def tarefas_do(cliente):
    return list(Tarefa.objects.filter(tipo=TIPO, cliente_id=cliente.pk))


# Página do cliente ---------------------------------------------------------------

def test_mostra_a_ultima_coleta_e_cada_parte(cenario, entrar_como):
    quando = datetime(2026, 11, 21, 13, 30, tzinfo=tz.utc)
    with contexto(organizacao_id=cenario.org_a.pk):
        ExecucaoColeta.objects.create(
            cliente=cenario.cliente_a, iniciada_em=quando, resultado="parcial",
            partes=[{"nome": "WAN", "ok": True, "mensagem": "166 hora(s)"},
                    {"nome": "Equipamentos", "ok": False, "mensagem": "A UniFi demorou demais para responder."}],
        )
        ConsoleEstado.objects.create(cliente=cenario.cliente_a, console=cenario.udr, coletado_em=quando)
    html = detalhe(entrar_como(cenario.admin_a), cenario.cliente_a)
    assert "21/11/2026 10:30" in html and "Parte falhou" in html
    assert "166 hora(s)" in html and "A UniFi demorou demais para responder." in html
    assert "21/11 10:30" in html  # última coleta do console, no horário de Brasília


def test_sem_coleta_ainda(cenario, entrar_como):
    html = detalhe(entrar_como(cenario.admin_a), cenario.cliente_a)
    assert "Nenhuma coleta ainda" in html


def test_sem_chave_nao_mostra_o_bloco_de_coletas(msps, entrar_como):
    html = detalhe(entrar_como(msps.admin_a), msps.cliente_a)
    assert "Coletar agora" not in html and "Nenhuma coleta ainda" not in html


def test_coleta_de_outra_organizacao_nao_aparece(cenario, entrar_como):
    with contexto(organizacao_id=cenario.org_b.pk):
        ExecucaoColeta.objects.create(cliente=cenario.cliente_b, resultado="ok",
                                      partes=[{"nome": "WAN", "ok": True, "mensagem": "segredo do B"}])
    assert "segredo do B" not in detalhe(entrar_como(cenario.admin_a), cenario.cliente_a)


# Coletar agora -----------------------------------------------------------------------

@pytest.mark.parametrize("quem", ["admin_a", "operador_a"])
def test_coletar_agora_enfileira_e_audita(cenario, entrar_como, quem):
    usuario = getattr(cenario, quem)
    html = coletar(entrar_como(usuario), cenario.cliente_a).content.decode()
    assert "Coleta na fila." in html
    (tarefa,) = tarefas_do(cenario.cliente_a)
    assert tarefa.organizacao_id == cenario.org_a.pk and tarefa.pedida_por_id == usuario.pk
    assert "Coleta na fila desde" in detalhe(entrar_como(usuario), cenario.cliente_a)
    with contexto(organizacao_id=cenario.org_a.pk):
        assert EventoOrganizacao.objects.filter(acao=Acao.COLETA_PEDIDA, usuario=usuario).exists()


def test_nao_duplica_coleta_na_fila(cenario, entrar_como):
    client = entrar_como(cenario.admin_a)
    coletar(client, cenario.cliente_a)
    html = coletar(client, cenario.cliente_a).content.decode()
    assert "Já há uma coleta deste cliente na fila." in html
    assert len(tarefas_do(cenario.cliente_a)) == 1


def test_no_maximo_uma_a_cada_10_minutos(cenario, entrar_como):
    client = entrar_como(cenario.admin_a)
    coletar(client, cenario.cliente_a)
    Tarefa.objects.update(situacao=Situacao.FEITA)  # a primeira já rodou
    html = coletar(client, cenario.cliente_a).content.decode()
    assert "Espere 10 minutos" in html
    assert len(tarefas_do(cenario.cliente_a)) == 1


def test_cliente_sem_console_acompanhado(cenario, entrar_como):
    with contexto(organizacao_id=cenario.org_a.pk):
        Console.objects.update(acompanhar=False)
    html = coletar(entrar_como(cenario.admin_a), cenario.cliente_a).content.decode()
    assert "pelo menos um console acompanhado" in html
    assert tarefas_do(cenario.cliente_a) == []


def test_leitura_nao_pede_coleta(cenario, entrar_como):
    client = entrar_como(cenario.leitor_a)
    assert client.post(reverse("coletas:coletar_agora", args=[cenario.cliente_a.pk])).status_code == 403
    assert "Coletar agora" not in detalhe(client, cenario.cliente_a)
    assert tarefas_do(cenario.cliente_a) == []


def test_nao_pede_coleta_de_cliente_de_outra_organizacao(cenario, entrar_como):
    resposta = entrar_como(cenario.admin_a).post(reverse("coletas:coletar_agora", args=[cenario.cliente_b.pk]))
    assert resposta.status_code == 404
    assert tarefas_do(cenario.cliente_b) == []


def test_coletar_agora_so_por_post(cenario, entrar_como):
    url = reverse("coletas:coletar_agora", args=[cenario.cliente_a.pk])
    assert entrar_como(cenario.admin_a).get(url).status_code == 405


# Retenção ---------------------------------------------------------------------------

def test_retencao_apaga_so_o_que_passou_do_prazo_em_todas_as_organizacoes(cenario):
    agora = timezone.now()
    for org, cliente, console in [(cenario.org_a, cenario.cliente_a, cenario.udr),
                                  (cenario.org_b, cenario.cliente_b, cenario.udr_b)]:
        base = {"cliente": cliente, "console": console}
        with contexto(organizacao_id=org.pk):
            for dias in (89, 91):
                EquipamentoAmostra.objects.create(**base, site_id="s", device_id=f"d{dias}",
                                                  coletado_em=agora - timedelta(days=dias))
                ClienteDia.objects.create(**base, site="default", mac=f"m{dias}", dia=(agora - timedelta(days=dias)).date())
            for dias in (300, 400):
                WanHora.objects.create(**base, site_id="s", horario=agora - timedelta(days=dias))
                InternetDia.objects.create(**base, site="default", dia=(agora - timedelta(days=dias)).date())

    apagadas = retencao.apagar_dados_antigos(agora)
    assert apagadas == {"coletas_equipamentoamostra": 2, "coletas_clientedia": 2,
                        "coletas_wanhora": 2, "coletas_internetdia": 2}
    for org in (cenario.org_a, cenario.org_b):
        with contexto(organizacao_id=org.pk):
            assert list(EquipamentoAmostra.objects.values_list("device_id", flat=True)) == ["d89"]
            assert WanHora.objects.count() == 1 and InternetDia.objects.count() == 1


def test_todas_as_tabelas_de_dado_coletado_tem_prazo():
    from django.apps import apps

    from coletas.models import DoConsole

    com_prazo = {m for m, _, _ in retencao.PRAZOS}
    coletados = {m for m in apps.get_app_config("coletas").get_models() if issubclass(m, DoConsole)}
    sem_prazo = {m.__name__ for m in coletados - com_prazo}
    # Sites e controle de frequência são atualizados no lugar (uma linha por site): não acumulam.
    assert sem_prazo == {"SiteNetwork", "ControleColeta"}


def test_periodicas_da_etapa_registradas():
    assert {"coletar_clientes", "apagar_dados_antigos", "limpar_tarefas"} <= set(periodicas())


# Resumo e catálogo --------------------------------------------------------------------

def test_resumo_cliente(cenario):
    with contexto(organizacao_id=cenario.org_a.pk):
        InternetDia.objects.create(cliente=cenario.cliente_a, console=cenario.udr, site="default",
                                   dia=timezone.localdate(), download_bytes=2_500_000_000, upload_bytes=0)
    saida = StringIO()
    call_command("resumo_cliente", cenario.cliente_a.pk, stdout=saida)
    texto = saida.getvalue()
    assert "Cliente: Padaria do A (MSP A)" in texto
    assert "WAN por dia" in texto and "2.50 GB" in texto


def test_resumo_de_cliente_inexistente():
    with pytest.raises(CommandError):
        call_command("resumo_cliente", 999999, stdout=StringIO())


def test_nomes_do_catalogo_juntam_categoria_e_aplicativo():
    Catalogo.objects.create(tipo="dpi_aplicativo", id_unifi=(13 << 16) | 94, nome="YouTube")
    Catalogo.objects.create(tipo="dpi_aplicativo", id_unifi=94, nome="Nome errado")
    Catalogo.objects.create(tipo="dpi_categoria", id_unifi=13, nome="Streaming")
    nomes = Nomes()
    assert nomes.aplicativo(13, 94) == "YouTube"
    assert nomes.aplicativo(255, 65535) == "Não identificado"
    assert nomes.aplicativo(1, 7) == "Aplicativo 7"
    assert nomes.categoria(13) == "Streaming"
