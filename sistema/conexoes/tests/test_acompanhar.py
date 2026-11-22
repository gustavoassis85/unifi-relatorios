"""Ligar e desligar o "acompanhar" de cada console."""
import pytest
from django.urls import reverse

from auditoria.models import Acao, EventoOrganizacao
from clientes.models import Cliente
from conexoes.models import Console
from organizacoes.isolamento import contexto

pytestmark = pytest.mark.django_db


def criar_console(org, cliente, host_id, nome, acompanhar=False, na_conta=True):
    with contexto(organizacao_id=org.pk):
        return Console.objects.create(
            cliente=cliente, host_id=host_id, nome=nome, conectado=na_conta,
            acompanhar=acompanhar, na_conta=na_conta,
        )


def recarregar(org, console):
    with contexto(organizacao_id=org.pk):
        return Console.objects.get(pk=console.pk)


def mudar(client, cliente, console, ligar):
    return client.post(
        reverse("conexoes:acompanhar", args=[cliente.pk, console.pk]),
        {"acompanhar": "1" if ligar else "0"},
        follow=True,
    )


def eventos(org):
    with contexto(organizacao_id=org.pk):
        return list(
            EventoOrganizacao.objects.filter(
                acao__in=[Acao.CONSOLE_ACOMPANHADO, Acao.CONSOLE_NAO_ACOMPANHADO]
            ).order_by("criado_em")
        )


@pytest.fixture
def cenario(msps):
    msps.udr = criar_console(msps.org_a, msps.cliente_a, "udr:1", "UDR Lab", acompanhar=True)
    msps.antigo = criar_console(msps.org_a, msps.cliente_a, "antigo:2", "Console antigo")
    msps.sumido = criar_console(msps.org_a, msps.cliente_a, "sumido:3", "Console sumido", na_conta=False)
    msps.do_b = criar_console(msps.org_b, msps.cliente_b, "escola:9", "Console da Escola", acompanhar=True)
    return msps


@pytest.mark.parametrize("quem", ["admin_a", "operador_a"])
def test_liga_e_desliga(cenario, entrar_como, quem):
    client = entrar_como(getattr(cenario, quem))
    html = mudar(client, cenario.cliente_a, cenario.antigo, True).content.decode()
    assert "Console antigo passou a ser acompanhado." in html
    assert recarregar(cenario.org_a, cenario.antigo).acompanhar is True

    html = mudar(client, cenario.cliente_a, cenario.udr, False).content.decode()
    assert "UDR Lab deixou de ser acompanhado." in html
    assert recarregar(cenario.org_a, cenario.udr).acompanhar is False

    ligou, desligou = eventos(cenario.org_a)
    assert ligou.acao == Acao.CONSOLE_ACOMPANHADO
    assert ligou.detalhes == {
        "cliente_id": cenario.cliente_a.pk, "cliente": "Padaria do A",
        "host_id": "antigo:2", "console": "Console antigo",
    }
    assert desligou.acao == Acao.CONSOLE_NAO_ACOMPANHADO


def test_pedir_o_que_ja_esta_nao_registra_nada(cenario, entrar_como):
    mudar(entrar_como(cenario.admin_a), cenario.cliente_a, cenario.udr, True)
    assert eventos(cenario.org_a) == []


def test_console_que_sumiu_da_conta_nao_pode_ser_ligado(cenario, entrar_como):
    client = entrar_como(cenario.admin_a)
    html = mudar(client, cenario.cliente_a, cenario.sumido, True).content.decode()
    assert "não aparece mais na conta" in html
    assert recarregar(cenario.org_a, cenario.sumido).acompanhar is False
    detalhe = client.get(reverse("clientes:detalhe", args=[cenario.cliente_a.pk])).content.decode()
    assert reverse("conexoes:acompanhar", args=[cenario.cliente_a.pk, cenario.sumido.pk]) not in detalhe


def test_console_que_sumiu_pode_ser_desligado(cenario, entrar_como):
    with contexto(organizacao_id=cenario.org_a.pk):
        Console.objects.filter(pk=cenario.udr.pk).update(na_conta=False)
    mudar(entrar_como(cenario.admin_a), cenario.cliente_a, cenario.udr, False)
    assert recarregar(cenario.org_a, cenario.udr).acompanhar is False


def test_console_acompanhado_em_outro_cliente_avisa_qual(cenario, entrar_como):
    with contexto(organizacao_id=cenario.org_a.pk):
        filial = Cliente.objects.create(nome="Filial do A")
    repetido = criar_console(cenario.org_a, filial, "udr:1", "UDR Lab")
    html = mudar(entrar_como(cenario.admin_a), filial, repetido, True).content.decode()
    assert "UDR Lab já é acompanhado no cliente Padaria do A." in html
    assert recarregar(cenario.org_a, repetido).acompanhar is False

    # Depois de desligar no primeiro cliente, dá para ligar no segundo.
    client = entrar_como(cenario.admin_a)
    mudar(client, cenario.cliente_a, cenario.udr, False)
    mudar(client, filial, repetido, True)
    assert recarregar(cenario.org_a, repetido).acompanhar is True


def test_leitura_nao_muda_nem_ve_os_botoes(cenario, entrar_como):
    client = entrar_como(cenario.leitor_a)
    resposta = client.post(
        reverse("conexoes:acompanhar", args=[cenario.cliente_a.pk, cenario.antigo.pk]), {"acompanhar": "1"}
    )
    assert resposta.status_code == 403
    assert recarregar(cenario.org_a, cenario.antigo).acompanhar is False
    html = client.get(reverse("clientes:detalhe", args=[cenario.cliente_a.pk])).content.decode()
    assert "/acompanhar/" not in html
    assert "Deixar de acompanhar" not in html


def test_so_por_post(cenario, entrar_como):
    url = reverse("conexoes:acompanhar", args=[cenario.cliente_a.pk, cenario.antigo.pk])
    assert entrar_como(cenario.admin_a).get(url).status_code == 405


# Isolamento ------------------------------------------------------------------------

def test_admin_de_a_nao_mexe_em_console_de_b(cenario, entrar_como):
    client = entrar_como(cenario.admin_a)
    pelo_cliente_b = reverse("conexoes:acompanhar", args=[cenario.cliente_b.pk, cenario.do_b.pk])
    pelo_cliente_a = reverse("conexoes:acompanhar", args=[cenario.cliente_a.pk, cenario.do_b.pk])
    assert client.post(pelo_cliente_b, {"acompanhar": "0"}).status_code == 404
    assert client.post(pelo_cliente_a, {"acompanhar": "0"}).status_code == 404
    assert recarregar(cenario.org_b, cenario.do_b).acompanhar is True
    assert eventos(cenario.org_b) == []


def test_console_de_outro_cliente_da_mesma_organizacao_pela_url_errada(cenario, entrar_como):
    with contexto(organizacao_id=cenario.org_a.pk):
        filial = Cliente.objects.create(nome="Filial do A")
    url = reverse("conexoes:acompanhar", args=[filial.pk, cenario.udr.pk])
    assert entrar_como(cenario.admin_a).post(url, {"acompanhar": "0"}).status_code == 404
    assert recarregar(cenario.org_a, cenario.udr).acompanhar is True


def test_aviso_de_outro_cliente_nunca_cita_cliente_de_outra_organizacao(cenario, entrar_como):
    # O MSP B acompanha um console com o mesmo hostId; para o A, isso não existe.
    criar_console(cenario.org_b, cenario.cliente_b, "antigo:2", "Console antigo", acompanhar=True)
    html = mudar(entrar_como(cenario.admin_a), cenario.cliente_a, cenario.antigo, True).content.decode()
    assert "Escola do B" not in html
    assert recarregar(cenario.org_a, cenario.antigo).acompanhar is True
