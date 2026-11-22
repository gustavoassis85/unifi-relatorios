"""Cria a tabela do cache compartilhado (usado pelo bloqueio de login).

Fica numa migração para receber as permissões do usuário da aplicação junto
com as outras tabelas, no banco real e no banco dos testes.
"""
from django.core.management import call_command
from django.db import migrations


def criar(apps, schema_editor):
    call_command("createcachetable", database=schema_editor.connection.alias, verbosity=0)


def apagar(apps, schema_editor):
    schema_editor.execute("drop table if exists cache_sistema")


class Migration(migrations.Migration):
    dependencies = [("contas", "0001_initial")]

    operations = [migrations.RunPython(criar, apagar)]
