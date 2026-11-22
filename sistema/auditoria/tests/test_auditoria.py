import json

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, transaction
from django.urls import reverse

from apoio_testes import SENHA, ativar_mfa, codigo_atual
from auditoria.models import Acao, EventoOrganizacao, EventoPlataforma
from auditoria.registro import limpar
from organizacoes.isolamento import contexto
from organizacoes.models import Papel

pytestmark = pytest.mark.django_db

URL_ADMIN = "/" + settings.ADMIN_URL


def eventos(org):
    with contexto(organizacao_id=org.pk):
        return list(EventoOrganizacao.objects.order_by("criado_em", "pk"))


def acoes(org):
    return [e.acao for e in eventos(org)]


def sql(texto, parametros=None):
    with connection.cursor() as cur:
        cur.execute(texto, parametros or [])
        return cur.fetchall() if cur.description else cur.rowcount


# Login, falha de login e logout


def test_login_gera_evento_na_organizacao_do_usuario(msps, client):
    client.post(reverse("account_login"), {"login": "op@a.com", "password": SENHA})
    evento = eventos(msps.org_a)[-1]
    assert evento.acao == Acao.LOGIN
    assert evento.usuario == msps.operador_a
    assert evento.ip == "127.0.0.1"
    assert evento.organizacao_id == msps.org_a.pk
    assert Acao.LOGIN not in acoes(msps.org_b)


def test_login_com_mfa_so_registra_depois_do_codigo(msps, client):
    segredo = ativar_mfa(msps.operador_a)
    client.post(reverse("account_login"), {"login": "op@a.com", "password": SENHA})
    assert Acao.LOGIN not in acoes(msps.org_a)
    client.post(reverse("mfa_authenticate"), {"code": codigo_atual(segredo)})
    assert acoes(msps.org_a).count(Acao.LOGIN) == 1


def test_falha_de_login_de_usuario_conhecido_vai_para_a_organizacao_dele(msps, client):
    client.post(reverse("account_login"), {"login": "op@a.com", "password": "errada-errada-1"})
    evento = eventos(msps.org_a)[-1]
    assert evento.acao == Acao.LOGIN_FALHOU
    assert evento.usuario == msps.operador_a
    assert Acao.LOGIN_FALHOU not in acoes(msps.org_b)


def test_falha_de_login_de_email_desconhecido_vai_para_a_plataforma(msps, client):
    client.post(reverse("account_login"), {"login": "ninguem@x.com", "password": "errada-errada-1"})
    evento = EventoPlataforma.objects.latest("criado_em")
    assert evento.acao == Acao.LOGIN_FALHOU
    assert evento.usuario is None
    assert evento.detalhes == {"email_digitado": "ninguem@x.com"}


def test_logout_gera_evento(msps, client):
    client.post(reverse("account_login"), {"login": "op@a.com", "password": SENHA})
    client.post(reverse("account_logout"))
    assert acoes(msps.org_a)[-1] == Acao.LOGOUT


# Clientes


def test_cliente_criado_alterado_e_apagado(msps, entrar_como):
    client = entrar_como(msps.operador_a)
    client.post(reverse("clientes:novo"), {"nome": "Oficina"})
    client.post(reverse("clientes:editar", args=[msps.cliente_a.pk]), {"nome": "Padaria Nova"})
    client.post(reverse("clientes:apagar", args=[msps.cliente_a.pk]))

    criado, alterado, apagado = [
        e for e in eventos(msps.org_a) if e.acao.startswith("cliente_")
    ]
    assert criado.acao == Acao.CLIENTE_CRIADO and criado.detalhes["nome"] == "Oficina"
    assert alterado.acao == Acao.CLIENTE_ALTERADO
    assert alterado.detalhes == {
        "cliente_id": msps.cliente_a.pk,
        "nome_antes": "Padaria do A",
        "nome_depois": "Padaria Nova",
    }
    assert apagado.acao == Acao.CLIENTE_APAGADO and apagado.detalhes["nome"] == "Padaria Nova"
    assert all(e.usuario == msps.operador_a for e in (criado, alterado, apagado))


def test_tentativa_recusada_nao_gera_evento(msps, entrar_como):
    entrar_como(msps.leitor_a).post(reverse("clientes:novo"), {"nome": "Não pode"})
    entrar_como(msps.admin_a).post(
        reverse("clientes:editar", args=[msps.cliente_b.pk]), {"nome": "Invadido"}
    )
    assert not [a for a in acoes(msps.org_a) if a.startswith("cliente_")]
    assert not [a for a in acoes(msps.org_b) if a.startswith("cliente_")]


# Usuários


def test_usuario_criado_e_alterado(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    client.post(
        reverse("usuarios:novo"),
        {"email": "novo@a.com", "nome": "Novo", "papel": Papel.OPERADOR, "senha1": SENHA, "senha2": SENHA},
    )
    novo = get_user_model().objects.get(email="novo@a.com")
    client.post(reverse("usuarios:editar", args=[novo.pk]), {"papel": Papel.LEITURA})

    criado, alterado = [e for e in eventos(msps.org_a) if e.acao.startswith("usuario_")][-2:]
    assert criado.acao == Acao.USUARIO_CRIADO
    assert criado.detalhes == {"alvo_id": novo.pk, "alvo_email": "novo@a.com", "papel": "operador"}
    assert alterado.acao == Acao.USUARIO_ALTERADO
    assert alterado.detalhes["antes"] == {"papel": "operador", "ativo": True}
    assert alterado.detalhes["depois"] == {"papel": "leitura", "ativo": False}
    assert criado.usuario == alterado.usuario == msps.admin_a


def test_dono_cria_organizacao_e_os_eventos_vao_para_os_lugares_certos(client):
    dono = get_user_model().objects.create_superuser("dono@plataforma.com", SENHA)
    ativar_mfa(dono)
    client.force_login(dono)
    client.post(
        URL_ADMIN + "organizacoes/organizacao/add/",
        {
            "nome": "MSP Novo",
            "admin_email": "chefe@novo.com",
            "admin_nome": "Chefe",
            "admin_senha1": SENHA,
            "admin_senha2": SENHA,
            "_save": "Salvar",
        },
    )
    from organizacoes.models import Organizacao

    org = Organizacao.objects.get(nome="MSP Novo")
    plataforma = EventoPlataforma.objects.get(acao=Acao.ORGANIZACAO_CRIADA)
    assert plataforma.usuario == dono and plataforma.detalhes["organizacao_id"] == org.pk
    (evento_org,) = eventos(org)
    assert evento_org.acao == Acao.USUARIO_CRIADO
    assert evento_org.detalhes["alvo_email"] == "chefe@novo.com"
    assert evento_org.usuario == dono


# Nada sensível


def test_nenhum_evento_guarda_senha_ou_codigo(msps, client, entrar_como):
    segredo = ativar_mfa(msps.operador_a)
    client.post(reverse("account_login"), {"login": "op@a.com", "password": "senha-errada-xyz"})
    client.post(reverse("account_login"), {"login": "op@a.com", "password": SENHA})
    codigo = codigo_atual(segredo)
    client.post(reverse("mfa_authenticate"), {"code": codigo})
    entrar_como(msps.admin_a).post(
        reverse("usuarios:novo"),
        {"email": "novo@a.com", "nome": "Novo", "papel": Papel.LEITURA, "senha1": SENHA, "senha2": SENHA},
    )

    todos = eventos(msps.org_a) + list(EventoPlataforma.objects.all())
    texto = json.dumps([e.detalhes for e in todos])
    assert len(todos) >= 4
    for proibido in (SENHA, "senha-errada-xyz", codigo, segredo):
        assert proibido not in texto


def test_limpar_descarta_campos_com_nome_sensivel():
    assert limpar(
        {"nome": "ok", "senha": "x", "password1": "x", "code": "1", "api_key": "k", "token": "t"}
    ) == {"nome": "ok"}


# Só de acréscimo


@pytest.mark.parametrize("tabela", ["auditoria_eventoorganizacao", "auditoria_eventoplataforma"])
def test_usuario_da_aplicacao_so_inclui_e_le_eventos(tabela):
    privilegios = {
        linha[0]
        for linha in sql(
            "select privilege_type from information_schema.role_table_grants "
            "where grantee = current_user and table_name = %s",
            [tabela],
        )
    }
    assert privilegios == {"INSERT", "SELECT"}


def test_evento_da_organizacao_nao_pode_ser_alterado_nem_apagado(msps, entrar_como):
    entrar_como(msps.operador_a).post(reverse("clientes:novo"), {"nome": "Oficina"})
    with contexto(organizacao_id=msps.org_a.pk):
        assert EventoOrganizacao.objects.exists()
        for comando in (
            "update auditoria_eventoorganizacao set acao = 'login'",
            "delete from auditoria_eventoorganizacao",
            "truncate auditoria_eventoorganizacao",
        ):
            with pytest.raises(DatabaseError), transaction.atomic():
                sql(comando)
        with pytest.raises(DatabaseError), transaction.atomic():
            EventoOrganizacao.objects.first().delete()


def test_evento_da_plataforma_nao_pode_ser_alterado_nem_apagado(client):
    client.post(reverse("account_login"), {"login": "ninguem@x.com", "password": "errada-errada-1"})
    assert EventoPlataforma.objects.exists()
    for comando in (
        "update auditoria_eventoplataforma set acao = 'login'",
        "delete from auditoria_eventoplataforma",
        "truncate auditoria_eventoplataforma",
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            sql(comando)


# Isolamento dos eventos


def test_eventos_de_uma_organizacao_nao_aparecem_para_outra(msps, entrar_como):
    entrar_como(msps.admin_b).post(reverse("clientes:novo"), {"nome": "Segredo do B"})
    with contexto(organizacao_id=msps.org_a.pk):
        texto = json.dumps([d for (d,) in sql("select detalhes::text from auditoria_eventoorganizacao")])
    assert "Segredo do B" not in texto
    assert sql("select count(*) from auditoria_eventoorganizacao")[0][0] == 0


def test_rls_ligada_e_forcada_nos_eventos_da_organizacao():
    ligada, forcada = sql(
        "select relrowsecurity, relforcerowsecurity from pg_class where relname = %s",
        ["auditoria_eventoorganizacao"],
    )[0]
    assert ligada and forcada
