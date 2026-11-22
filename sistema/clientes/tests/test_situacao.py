"""Tela de clientes em quadros e lista, painel lateral com busca e filtro: situação certa e isolamento."""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from clientes.models import Cliente
from clientes.situacao import filtrar, situacao_dos_clientes
from coletas.models import ExecucaoColeta
from conexoes.models import ChaveUniFi, Console
from organizacoes.isolamento import contexto

pytestmark = pytest.mark.django_db


def preparar(org, cliente, *, chave=True, teste_ok=True, consoles=1, coletas=()):
    """coletas: [(horas atrás, resultado)]"""
    agora = timezone.now()
    with contexto(organizacao_id=org.pk):
        if chave:
            c = ChaveUniFi(cliente=cliente, teste_ok=teste_ok)
            c.definir("chave-de-teste-0123456789")
            c.save()
        for i in range(consoles):
            Console.objects.create(cliente=cliente, host_id=f"h{cliente.pk}:{i}", nome=f"C{i}", acompanhar=True,
                                   na_conta=True, primeiro_visto_em=agora, visto_em=agora)
        for horas, resultado in coletas:
            quando = agora - timedelta(hours=horas)
            ExecucaoColeta.objects.create(cliente=cliente, iniciada_em=quando, terminada_em=quando,
                                          resultado=resultado)


def situacao(org, cliente):
    with contexto(organizacao_id=org.pk):
        [s] = situacao_dos_clientes([Cliente.objects.get(pk=cliente.pk)])
    return s


def test_coletando(msps):
    preparar(msps.org_a, msps.cliente_a, coletas=[(3, "ok"), (2, "parcial"), (0.2, "ok")])
    s = situacao(msps.org_a, msps.cliente_a)
    assert (s.estado, s.resumo) == ("ok", "1 console acompanhado")
    assert s.horas[-1] == "ok" and s.horas.count("parcial") == 1 and s.horas_ok == 2 and s.horas_com_coleta == 3


@pytest.mark.parametrize("opcoes, estado, resumo", [
    ({"chave": False, "consoles": 0}, "sem_coleta", "Sem chave da UniFi"),
    ({"consoles": 0}, "sem_coleta", "Nenhum console acompanhado"),
    ({}, "sem_coleta", "Ainda sem coleta"),
    ({"teste_ok": False, "coletas": [(0.2, "ok")]}, "falha", "O último teste de conexão falhou"),
    ({"coletas": [(0.2, "falhou")]}, "falha", "A última coleta falhou"),
    ({"coletas": [(5, "ok")]}, "atencao", "Sem coleta há 5 horas"),
    ({"consoles": 2, "coletas": [(0.2, "parcial")]}, "atencao", "2 consoles acompanhados; parte da última coleta falhou"),
])
def test_cada_situacao(msps, opcoes, estado, resumo):
    preparar(msps.org_a, msps.cliente_a, **opcoes)
    s = situacao(msps.org_a, msps.cliente_a)
    assert (s.estado, s.resumo) == (estado, resumo)


def test_coleta_rodando_e_mais_antiga_que_24h_nao_entram_na_faixa(msps):
    preparar(msps.org_a, msps.cliente_a, coletas=[(30, "ok"), (0.1, "rodando")])
    s = situacao(msps.org_a, msps.cliente_a)
    assert s.horas_com_coleta == 0 and s.estado == "atencao"   # última terminada foi há 30 h


def test_filtrar():
    class S:
        def __init__(self, nome, estado):
            self.cliente = type("C", (), {"nome": nome})()
            self.estado = estado
    lista = [S("Padaria", "ok"), S("Escola", "falha"), S("Loja", "sem_coleta"), S("Posto", "atencao")]
    assert [s.cliente.nome for s in filtrar(lista, "problema")] == ["Escola", "Posto"]
    assert [s.cliente.nome for s in filtrar(lista, "sem_coleta")] == ["Loja"]
    assert [s.cliente.nome for s in filtrar(lista, "todos", "  ESC ")] == ["Escola"]


def test_quadros_lista_e_painel(msps, entrar_como):
    preparar(msps.org_a, msps.cliente_a, coletas=[(0.2, "ok")])
    client = entrar_como(msps.leitor_a)
    html = client.get(reverse("clientes:lista")).content.decode()
    assert 'class="quadro-cliente"' in html and "1 console acompanhado" in html and "1 de 24 horas" in html
    assert 'id="painel-clientes"' in html and "Cadastrar cliente" not in html
    html = client.get(reverse("clientes:lista") + "?visao=lista").content.decode()
    assert "<table>" in html and "1 de 24 ok" in html and "Editar" not in html
    html = client.get(reverse("clientes:painel"), {"busca": "padaria"}).content.decode()
    assert "Padaria do A" in html
    html = client.get(reverse("clientes:painel"), {"busca": "xyz"}).content.decode()
    assert "Nenhum cliente com esse filtro." in html
    html = client.get(reverse("clientes:painel"), {"situacao": "sem_coleta"}).content.decode()
    assert "Padaria do A" not in html


def test_painel_marca_o_cliente_aberto_e_some_fora_de_clientes(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    html = client.get(reverse("clientes:detalhe", args=[msps.cliente_a.pk])).content.decode()
    assert 'aria-current="page"' in html.split('id="lista-painel"')[1].split("</ul>")[0]
    assert 'id="painel-clientes"' not in client.get(reverse("relatorios:marca")).content.decode()


def test_msp_a_nao_ve_clientes_nem_situacao_do_b(msps, entrar_como):
    preparar(msps.org_b, msps.cliente_b, coletas=[(0.2, "ok")])
    client = entrar_como(msps.admin_a)
    for url in (reverse("clientes:lista"), reverse("clientes:lista") + "?visao=lista",
                reverse("clientes:painel") + "?busca=escola", reverse("clientes:detalhe", args=[msps.cliente_a.pk])):
        assert "Escola do B" not in client.get(url).content.decode()
    # pedir a situação de clientes do B com a organização do A não devolve nada do B
    with contexto(organizacao_id=msps.org_a.pk):
        [s] = situacao_dos_clientes([msps.cliente_b])
    assert s.horas_com_coleta == 0 and s.resumo == "Sem chave da UniFi"


def test_menu_marca_a_secao_atual(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    html = client.get(reverse("relatorios:marca")).content.decode()
    assert 'aria-label="Marca dos relatórios" aria-current="page"' in " ".join(html.split())
    html = " ".join(client.get(reverse("clientes:lista")).content.decode().split())
    assert 'aria-label="Clientes" aria-current="page"' in html
    assert 'aria-label="Marca dos relatórios" aria-current' not in html
