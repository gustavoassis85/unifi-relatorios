"""Permissões do usuário da aplicação no banco.

Roda depois de cada migração (no banco real e no banco temporário dos testes),
conectado como o dono das tabelas. Assim o usuário da aplicação só recebe o que precisa.
"""
from django.conf import settings
from django.db import connection
from psycopg import sql

# Tabelas que o usuário da aplicação só pode ler.
SOMENTE_LEITURA = ["django_migrations"]

# Tabelas só de acréscimo (auditoria): leitura e inclusão, sem alterar nem apagar.
SO_ACRESCIMO = []


def tabelas_existentes():
    with connection.cursor() as cur:
        cur.execute("select tablename from pg_tables where schemaname = 'public'")
        return {linha[0] for linha in cur.fetchall()}


def aplicar_permissoes(**kwargs):
    if connection.vendor != "postgresql" or settings.DB_PAPEL != "dono":
        return
    app = sql.Identifier(settings.DB_APP_USUARIO)
    existentes = tabelas_existentes()
    with connection.cursor() as cur:
        cur.execute(sql.SQL("grant usage on schema public to {}").format(app))
        cur.execute(
            sql.SQL(
                "grant select, insert, update, delete on all tables in schema public to {}"
            ).format(app)
        )
        cur.execute(
            sql.SQL("grant usage, select on all sequences in schema public to {}").format(app)
        )
        for tabela in SOMENTE_LEITURA:
            if tabela in existentes:
                cur.execute(
                    sql.SQL("revoke insert, update, delete on {} from {}").format(
                        sql.Identifier(tabela), app
                    )
                )
        for tabela in SO_ACRESCIMO:
            if tabela in existentes:
                cur.execute(
                    sql.SQL("revoke update, delete, truncate on {} from {}").format(
                        sql.Identifier(tabela), app
                    )
                )
