import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings
from django.core import checks
from django.test import Client
from django.urls import reverse

from apoio_testes import SENHA

pytestmark = pytest.mark.django_db

PASTA_SISTEMA = Path(__file__).resolve().parents[2]


# Cabeçalhos


def test_cabecalhos_de_seguranca(client):
    resposta = client.get(reverse("account_login"))
    csp = resposta["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert resposta["X-Frame-Options"] == "DENY"
    assert resposta["X-Content-Type-Options"] == "nosniff"
    assert resposta["Referrer-Policy"] == "same-origin"


def test_telas_nao_tem_script_inline(msps, entrar_como):
    """Todo script executável vem de arquivo do próprio sistema (a CSP bloquearia o resto)."""
    client = entrar_como(msps.admin_a)
    paginas = [reverse("clientes:lista"), reverse("usuarios:lista"), reverse("usuarios:novo")]
    for pagina in paginas + [reverse("account_login")]:
        html = client.get(pagina).content.decode()
        for tag in re.findall(r"<script[^>]*>", html):
            assert "src=" in tag or 'type="application/json"' in tag, (pagina, tag)
        assert " style=" not in html, pagina


# Cookies


def test_cookies_seguros_apos_login(msps, client):
    client.get(reverse("account_login"))
    client.post(reverse("account_login"), {"login": "op@a.com", "password": SENHA})
    sessao = client.cookies[settings.SESSION_COOKIE_NAME]
    assert sessao["secure"] and sessao["httponly"] and sessao["samesite"] == "Lax"
    csrf = client.cookies[settings.CSRF_COOKIE_NAME]
    assert csrf["secure"] and csrf["httponly"] and csrf["samesite"] == "Strict"


def test_csrf_recusa_formulario_sem_token(msps):
    client = Client(enforce_csrf_checks=True)
    client.force_login(msps.operador_a)
    resposta = client.post(reverse("clientes:novo"), {"nome": "Sem token"})
    assert resposta.status_code == 403


# Endereços


def test_admin_do_django_nao_fica_em_barra_admin(client):
    assert client.get("/admin/").status_code == 404


def test_usuario_nao_troca_o_proprio_email(msps, entrar_como):
    client = entrar_como(msps.operador_a)
    assert client.get("/contas/email/").status_code == 404
    assert client.post("/contas/email/", {"email": "outro@x.com", "action_add": ""}).status_code == 404


# check --deploy


def test_check_deploy_so_aponta_os_itens_de_https():
    avisos = checks.run_checks(include_deployment_checks=True)
    ids = {aviso.id for aviso in avisos}
    assert ids <= {"security.W004", "security.W008"}, [str(a) for a in avisos]


# Configurações vindas do ambiente


def carregar_settings(**variaveis):
    """Carrega as configurações num processo separado, com o ambiente alterado."""
    ambiente = {**os.environ, **variaveis}
    return subprocess.run(
        [sys.executable, "-c", "import config.settings as s; print(s.DEBUG)"],
        cwd=PASTA_SISTEMA,
        env=ambiente,
        capture_output=True,
        text=True,
    )


def test_debug_desligado_quando_nao_definido():
    resultado = carregar_settings(DJANGO_DEBUG="")
    assert resultado.stdout.strip() == "False"


def test_sem_secret_key_o_sistema_nao_sobe():
    resultado = carregar_settings(DJANGO_SECRET_KEY="")
    assert resultado.returncode != 0
    assert "DJANGO_SECRET_KEY" in resultado.stderr


def test_admin_em_barra_admin_e_recusado():
    resultado = carregar_settings(DJANGO_ADMIN_URL="admin/")
    assert resultado.returncode != 0
