"""Preparação dos testes.

O banco temporário dos testes é criado e migrado pelo usuário dono (que pode criar bancos).
Depois disso, todos os testes rodam conectados como o usuário da aplicação, o mesmo do
sistema em funcionamento: é com ele que o isolamento precisa ser provado.
"""
import os

import pytest
from django.db import connections


def conectar_como(papel):
    conexao = connections["default"]
    conexao.close()
    conexao.settings_dict["USER"] = os.environ[f"DB_{papel}_USUARIO"]
    conexao.settings_dict["PASSWORD"] = os.environ[f"DB_{papel}_SENHA"]


@pytest.fixture(scope="session")
def django_db_setup(django_test_environment, django_db_blocker):
    from django.conf import settings
    from django.test.utils import setup_databases, teardown_databases

    papel_original = settings.DB_PAPEL
    settings.DB_PAPEL = "dono"  # libera as permissões dadas depois da migração
    conectar_como("DONO")
    with django_db_blocker.unblock():
        configuracao = setup_databases(verbosity=0, interactive=False)
    settings.DB_PAPEL = papel_original

    conectar_como("APP")
    yield

    conectar_como("DONO")
    with django_db_blocker.unblock():
        teardown_databases(configuracao, verbosity=0)


@pytest.fixture(autouse=True)
def senhas_rapidas_nos_testes(settings):
    # Só nos testes: o embaralhamento forte de senha deixaria a bateria muito lenta.
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture
def msps(db):
    """Dois MSPs: A com admin, operador e leitura; B com admin. Um cliente em cada."""
    from types import SimpleNamespace

    from apoio_testes import SENHA, ativar_mfa
    from clientes.models import Cliente
    from organizacoes.isolamento import contexto
    from organizacoes.models import Papel
    from organizacoes.servicos import criar_organizacao_com_admin, criar_usuario_na_organizacao

    org_a, admin_a = criar_organizacao_com_admin("MSP A", "admin@a.com", "Ana", SENHA)
    org_b, admin_b = criar_organizacao_com_admin("MSP B", "admin@b.com", "Bia", SENHA)
    ativar_mfa(admin_a)
    ativar_mfa(admin_b)
    with contexto(organizacao_id=org_a.pk):
        operador_a = criar_usuario_na_organizacao(org_a, "op@a.com", "Otto", SENHA, Papel.OPERADOR)
        leitor_a = criar_usuario_na_organizacao(org_a, "leitor@a.com", "Leo", SENHA, Papel.LEITURA)
        cliente_a = Cliente.objects.create(nome="Padaria do A")
    with contexto(organizacao_id=org_b.pk):
        cliente_b = Cliente.objects.create(nome="Escola do B")
    return SimpleNamespace(
        org_a=org_a, org_b=org_b,
        admin_a=admin_a, admin_b=admin_b, operador_a=operador_a, leitor_a=leitor_a,
        cliente_a=cliente_a, cliente_b=cliente_b,
    )


@pytest.fixture
def entrar_como(client):
    def entrar(usuario):
        client.force_login(usuario)
        return client

    return entrar
