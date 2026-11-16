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
