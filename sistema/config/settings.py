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
    "allauth",
    "allauth.account",
    "allauth.mfa",
    "contas",
    "organizacoes",
    "clientes",
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
    "allauth.account.middleware.AccountMiddleware",
    # Define o usuário e a organização da requisição no banco (RLS).
    "organizacoes.middleware.ContextoOrganizacaoMiddleware",
    # Quem precisa de MFA e ainda não configurou só acessa a tela de configurar.
    "contas.middleware.MfaObrigatorioMiddleware",
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
                "organizacoes.permissoes.para_templates",
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

# Login (django-allauth): e-mail e senha, sem cadastro aberto (usuários são criados
# pelo admin da organização ou pelo dono da plataforma).
AUTHENTICATION_BACKENDS = ["allauth.account.auth_backends.AuthenticationBackend"]
ACCOUNT_ADAPTER = "contas.adaptadores.AdaptadorContas"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_SESSION_REMEMBER = False
ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE = True
ACCOUNT_PREVENT_ENUMERATION = True
# Bloqueio temporário: 5 senhas erradas para o mesmo e-mail travam por 15 minutos;
# 10 tentativas por minuto do mesmo IP também travam.
ACCOUNT_RATE_LIMITS = {"login_failed": "10/m/ip,5/900s/key"}
LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "inicio"
ACCOUNT_LOGOUT_REDIRECT_URL = "account_login"

# MFA: app autenticador (TOTP) e códigos de recuperação.
MFA_SUPPORTED_TYPES = ["totp", "recovery_codes"]
MFA_TOTP_ISSUER = "Dashboard UniFi"
MFA_PASSKEY_LOGIN_ENABLED = False
MFA_TRUST_ENABLED = False

# Cache compartilhado no banco: o bloqueio de login vale para todos os processos.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "cache_sistema",
    }
}

# Sessão: expira após 2 horas sem uso e ao fechar o navegador.
SESSION_COOKIE_AGE = 2 * 60 * 60
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# E-mail: o SMTP chega numa etapa futura. Por enquanto, mensagens vão para o terminal.
EMAIL_BACKEND = os.environ.get(
    "DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
