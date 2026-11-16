"""Configurações do sistema. Todo valor sensível vem do ambiente (.env no desenvolvimento)."""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Variáveis já definidas no ambiente têm prioridade sobre o .env.
load_dotenv(BASE_DIR / ".env", override=False)


def obrigatorio(nome):
    valor = os.environ.get(nome, "")
    if not valor:
        raise ImproperlyConfigured(f"Falta a configuração {nome} no ambiente ou no .env.")
    return valor


def lista(nome, padrao=""):
    return [item.strip() for item in os.environ.get(nome, padrao).split(",") if item.strip()]


SECRET_KEY = obrigatorio("DJANGO_SECRET_KEY")
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = lista("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

ADMIN_URL = obrigatorio("DJANGO_ADMIN_URL")
if not ADMIN_URL.endswith("/") or ADMIN_URL.strip("/") == "admin":
    raise ImproperlyConfigured("DJANGO_ADMIN_URL deve terminar com / e não pode ser admin/.")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "contas",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Banco: o sistema conecta como o usuário da aplicação (sem poderes extras).
# Só os comandos de migração (ver manage.py) usam o dono das tabelas.
DB_PAPEL = os.environ.get("DJANGO_DB_PAPEL", "app")
if DB_PAPEL not in ("app", "dono"):
    raise ImproperlyConfigured("DJANGO_DB_PAPEL deve ser app ou dono.")
_papel = DB_PAPEL.upper()

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": obrigatorio("DB_NOME"),
        "USER": obrigatorio(f"DB_{_papel}_USUARIO"),
        "PASSWORD": obrigatorio(f"DB_{_papel}_SENHA"),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORTA", "5432"),
        # Cada requisição roda dentro de uma transação: é nela que a organização
        # será definida (set_config local), e ela some ao fim da requisição.
        "ATOMIC_REQUESTS": True,
    }
}

# Nome do usuário da aplicação, usado nas permissões dadas depois de cada migração.
DB_APP_USUARIO = obrigatorio("DB_APP_USUARIO")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "contas.Usuario"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
