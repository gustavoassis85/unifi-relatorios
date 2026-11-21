"""Cria o sistema/.env com valores aleatórios (chave do Django e senhas do banco).

Uso (dentro de sistema/):  python scripts\\gerar_env.py
Não sobrescreve um .env existente e não mostra nenhum valor na tela.
"""
import pathlib
import secrets
import sys

ARQUIVO = pathlib.Path(__file__).resolve().parent.parent / ".env"

if ARQUIVO.exists():
    sys.exit("sistema/.env já existe; nada foi alterado.")

valores = {
    "DJANGO_SECRET_KEY": secrets.token_urlsafe(50),
    "DJANGO_DEBUG": "0",
    "DJANGO_ALLOWED_HOSTS": "localhost,127.0.0.1",
    "DJANGO_ADMIN_URL": "plataforma-" + secrets.token_hex(6) + "/",
    "DJANGO_HTTPS": "0",
    "DB_NOME": "unifi_sistema",
    "DB_HOST": "localhost",
    "DB_PORTA": "5432",
    "DB_DONO_USUARIO": "unifi_dono",
    "DB_DONO_SENHA": secrets.token_urlsafe(32),
    "DB_APP_USUARIO": "unifi_app",
    "DB_APP_SENHA": secrets.token_urlsafe(32),
}
ARQUIVO.write_text("".join(f"{k}={v}\n" for k, v in valores.items()), encoding="utf-8")
print("sistema/.env criado. Tamanho de cada valor:", {k: len(v) for k, v in valores.items()})
