import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse

from apoio_testes import SENHA, ativar_mfa, codigo_atual
from organizacoes.isolamento import contexto
from organizacoes.models import Papel
from organizacoes.servicos import criar_organizacao_com_admin, criar_usuario_na_organizacao

pytestmark = pytest.mark.django_db

URL_ADMIN = "/" + settings.ADMIN_URL
URL_LOGIN = reverse("account_login")
URL_ATIVAR_MFA = reverse("mfa_activate_totp")
URL_CODIGO_MFA = reverse("mfa_authenticate")
URL_CONFIRMAR_SENHA = reverse("account_reauthenticate")
URL_CLIENTES = reverse("clientes:lista")


def entrar(client, email, senha=SENHA):
    return client.post(URL_LOGIN, {"login": email, "password": senha})


@pytest.fixture
def org_e_admin():
    return criar_organizacao_com_admin("MSP A", "admin@a.com", "Ana", SENHA)


@pytest.fixture
def operador(org_e_admin):
    org, _ = org_e_admin
    with contexto(organizacao_id=org.pk):
        return criar_usuario_na_organizacao(org, "op@a.com", "Otto", SENHA, Papel.OPERADOR)


@pytest.fixture
def dono():
    return get_user_model().objects.create_superuser("dono@plataforma.com", SENHA)


# Login e sessão


def test_operador_entra_com_email_e_senha(client, operador):
    resposta = entrar(client, "OP@a.com")
    assert resposta.status_code == 302
    assert client.get(URL_CLIENTES).status_code == 200


def test_senha_errada_nao_entra(client, operador):
    resposta = entrar(client, "op@a.com", "senha-errada-123456")
    assert resposta.status_code == 200
    assert client.get(reverse("inicio")).status_code == 302


def test_sem_login_vai_para_a_tela_de_login(client):
    resposta = client.get(reverse("inicio"))
    assert resposta.status_code == 302
    assert resposta["Location"].startswith(URL_LOGIN)


def test_logout_encerra_a_sessao(client, operador):
    entrar(client, "op@a.com")
    client.post(reverse("account_logout"))
    assert client.get(reverse("inicio")).status_code == 302


def test_sessao_expira():
    assert settings.SESSION_COOKIE_AGE <= 2 * 60 * 60
    assert settings.SESSION_SAVE_EVERY_REQUEST
    assert settings.SESSION_EXPIRE_AT_BROWSER_CLOSE


def test_nao_ha_cadastro_aberto(client):
    client.post(
        reverse("account_signup"),
        {"email": "novo@x.com", "password1": SENHA, "password2": SENHA},
    )
    assert not get_user_model().objects.filter(email="novo@x.com").exists()


# Bloqueio


def test_bloqueio_apos_tentativas_erradas(client, operador):
    for _ in range(5):
        entrar(client, "op@a.com", "senha-errada-123456")
    # Mesmo com a senha certa, o e-mail está bloqueado por um tempo.
    resposta = entrar(client, "op@a.com")
    assert resposta.status_code in (200, 429)
    assert client.get(reverse("inicio")).status_code == 302


def test_bloqueio_usa_cache_compartilhado_no_banco():
    assert settings.CACHES["default"]["BACKEND"] == "django.core.cache.backends.db.DatabaseCache"


# MFA


def test_admin_sem_mfa_so_acessa_a_configuracao_do_mfa(client, org_e_admin):
    entrar(client, "admin@a.com")
    resposta = client.get(reverse("inicio"))
    assert resposta.status_code == 302
    assert resposta["Location"] == URL_ATIVAR_MFA
    # Ligar o MFA pede a senha de novo (proteção do allauth); essa tela também é liberada.
    resposta = client.get(URL_ATIVAR_MFA)
    assert resposta["Location"].startswith(URL_CONFIRMAR_SENHA)
    client.post(URL_CONFIRMAR_SENHA, {"password": SENHA})
    assert client.get(URL_ATIVAR_MFA).status_code == 200
    # Outras telas continuam bloqueadas até o MFA ser configurado.
    assert client.get(reverse("inicio"))["Location"] == URL_ATIVAR_MFA


def test_admin_configura_o_mfa_e_passa_a_entrar(client, org_e_admin):
    entrar(client, "admin@a.com")
    client.post(URL_CONFIRMAR_SENHA, {"password": SENHA})
    pagina = client.get(URL_ATIVAR_MFA)
    segredo = pagina.context["form"].secret
    client.post(URL_ATIVAR_MFA, {"code": codigo_atual(segredo)})
    assert client.get(URL_CLIENTES).status_code == 200


def test_admin_sem_mfa_ainda_consegue_sair(client, org_e_admin):
    entrar(client, "admin@a.com")
    resposta = client.post(reverse("account_logout"))
    assert resposta.status_code == 302
    assert resposta["Location"] != URL_ATIVAR_MFA


def test_operador_nao_e_obrigado_a_ter_mfa(client, operador):
    entrar(client, "op@a.com")
    assert client.get(URL_CLIENTES).status_code == 200


def test_admin_com_mfa_precisa_do_codigo_para_entrar(client, org_e_admin):
    _, admin = org_e_admin
    segredo = ativar_mfa(admin)
    resposta = entrar(client, "admin@a.com")
    assert resposta.status_code == 302
    assert resposta["Location"].startswith(URL_CODIGO_MFA)
    # Só com a senha ainda não entrou.
    assert client.get(reverse("inicio")).status_code == 302

    resposta = client.post(URL_CODIGO_MFA, {"code": codigo_atual(segredo)})
    assert resposta.status_code == 302
    assert client.get(URL_CLIENTES).status_code == 200


def test_codigo_errado_nao_entra(client, org_e_admin):
    _, admin = org_e_admin
    segredo = ativar_mfa(admin)
    entrar(client, "admin@a.com")
    errado = str((int(codigo_atual(segredo)) + 1) % 1_000_000).zfill(6)
    client.post(URL_CODIGO_MFA, {"code": errado})
    assert client.get(reverse("inicio")).status_code == 302


def test_dono_sem_mfa_nao_acessa_o_admin(client, dono):
    entrar(client, "dono@plataforma.com")
    resposta = client.get(URL_ADMIN)
    assert resposta.status_code == 302
    assert resposta["Location"] == URL_ATIVAR_MFA


def test_dono_com_mfa_acessa_o_admin(client, dono):
    segredo = ativar_mfa(dono)
    entrar(client, "dono@plataforma.com")
    client.post(URL_CODIGO_MFA, {"code": codigo_atual(segredo)})
    assert client.get(URL_ADMIN).status_code == 200


# Admin do Django sem login próprio


def test_admin_do_django_manda_para_o_login_do_sistema(client):
    resposta = client.get(URL_ADMIN)
    assert resposta.status_code == 302
    destino = client.get(resposta["Location"])
    assert destino.status_code == 302
    assert destino["Location"].startswith(URL_LOGIN)


def test_login_do_admin_nunca_aceita_senha(client, dono, operador):
    # Mesmo logado como operador, mandar a senha do dono para o login do admin
    # não troca de usuário (e não pula o MFA do dono).
    ativar_mfa(dono)
    entrar(client, "op@a.com")
    client.post(
        reverse("admin:login"), {"username": "dono@plataforma.com", "password": SENHA}
    )
    assert client.get(URL_ADMIN).status_code == 302
    assert client.get(URL_CLIENTES).context["user"].email == "op@a.com"
