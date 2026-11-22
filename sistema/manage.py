#!/usr/bin/env python
"""Comando principal do Django."""
import os
import sys

# Comandos que mexem na estrutura do banco rodam como o usuário dono das tabelas.
# Todo o resto (inclusive o servidor) roda como o usuário da aplicação.
COMANDOS_DO_DONO = {"migrate", "makemigrations", "sqlmigrate", "showmigrations"}


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    if len(sys.argv) > 1 and sys.argv[1] in COMANDOS_DO_DONO:
        os.environ.setdefault("DJANGO_DB_PAPEL", "dono")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
