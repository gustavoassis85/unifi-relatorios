import pytest
from django.urls import reverse

from clientes.models import Cliente
from organizacoes.isolamento import contexto

pytestmark = pytest.mark.django_db


def nomes_no_banco(org):
    with contexto(organizacao_id=org.pk):
        return set(Cliente.objects.values_list("nome", flat=True))


# Isolamento pela tela: MSP A nunca alcança cliente do MSP B (404)


def test_lista_mostra_so_clientes_da_propria_organizacao(msps, entrar_como):
    resposta = entrar_como(msps.admin_a).get(reverse("clientes:lista"))
    assert resposta.status_code == 200
    assert "Padaria do A" in resposta.content.decode()
    assert "Escola do B" not in resposta.content.decode()


def test_nao_abre_cliente_de_outra_organizacao(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    assert client.get(reverse("clientes:editar", args=[msps.cliente_b.pk])).status_code == 404
    assert client.get(reverse("clientes:apagar", args=[msps.cliente_b.pk])).status_code == 404


def test_nao_edita_cliente_de_outra_organizacao(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    resposta = client.post(
        reverse("clientes:editar", args=[msps.cliente_b.pk]), {"nome": "Invadido"}
    )
    assert resposta.status_code == 404
    assert nomes_no_banco(msps.org_b) == {"Escola do B"}


def test_nao_apaga_cliente_de_outra_organizacao(msps, entrar_como):
    client = entrar_como(msps.operador_a)
    resposta = client.post(reverse("clientes:apagar", args=[msps.cliente_b.pk]))
    assert resposta.status_code == 404
    assert nomes_no_banco(msps.org_b) == {"Escola do B"}


def test_cliente_novo_fica_na_organizacao_de_quem_cadastrou(msps, entrar_como):
    client = entrar_como(msps.operador_a)
    resposta = client.post(reverse("clientes:novo"), {"nome": "Mercado do A"})
    assert resposta.status_code == 302
    assert "Mercado do A" in nomes_no_banco(msps.org_a)
    assert "Mercado do A" not in nomes_no_banco(msps.org_b)


def test_campo_de_organizacao_enviado_pela_tela_e_ignorado(msps, entrar_como):
    client = entrar_como(msps.operador_a)
    client.post(reverse("clientes:novo"), {"nome": "Esperto", "organizacao": msps.org_b.pk})
    assert "Esperto" in nomes_no_banco(msps.org_a)
    assert "Esperto" not in nomes_no_banco(msps.org_b)


def test_mesmo_nome_pode_existir_em_organizacoes_diferentes(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    resposta = client.post(reverse("clientes:novo"), {"nome": "Escola do B"})
    assert resposta.status_code == 302
    assert "Escola do B" in nomes_no_banco(msps.org_a)


def test_nome_repetido_na_mesma_organizacao_e_recusado(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    resposta = client.post(reverse("clientes:novo"), {"nome": "padaria do a"})
    assert resposta.status_code == 200
    assert "Já existe um cliente com este nome." in resposta.content.decode()


# Papéis


def test_leitura_ve_a_lista_mas_nao_cria_nem_edita(msps, entrar_como):
    client = entrar_como(msps.leitor_a)
    lista = client.get(reverse("clientes:lista"))
    assert lista.status_code == 200
    assert "Cadastrar cliente" not in lista.content.decode()
    assert client.get(reverse("clientes:novo")).status_code == 403
    assert client.post(reverse("clientes:novo"), {"nome": "Não pode"}).status_code == 403
    editar = reverse("clientes:editar", args=[msps.cliente_a.pk])
    assert client.post(editar, {"nome": "Não pode"}).status_code == 403
    apagar = reverse("clientes:apagar", args=[msps.cliente_a.pk])
    assert client.post(apagar).status_code == 403
    assert nomes_no_banco(msps.org_a) == {"Padaria do A"}


def test_operador_cria_edita_e_apaga(msps, entrar_como):
    client = entrar_como(msps.operador_a)
    client.post(reverse("clientes:novo"), {"nome": "Oficina"})
    client.post(reverse("clientes:editar", args=[msps.cliente_a.pk]), {"nome": "Padaria Nova"})
    assert nomes_no_banco(msps.org_a) == {"Oficina", "Padaria Nova"}
    client.post(reverse("clientes:apagar", args=[msps.cliente_a.pk]))
    assert nomes_no_banco(msps.org_a) == {"Oficina"}


def test_dono_da_plataforma_nao_usa_as_telas_de_clientes(msps, entrar_como):
    from django.contrib.auth import get_user_model

    from apoio_testes import SENHA, ativar_mfa

    dono = get_user_model().objects.create_superuser("dono@plataforma.com", SENHA)
    ativar_mfa(dono)
    assert entrar_como(dono).get(reverse("clientes:lista")).status_code == 403


def test_sem_login_vai_para_o_login(client):
    resposta = client.get(reverse("clientes:lista"))
    assert resposta.status_code == 302
    assert resposta["Location"].startswith(reverse("account_login"))
