import pytest
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.db import IntegrityError, connection, transaction

pytestmark = pytest.mark.django_db


def consultar(sql_texto):
    with connection.cursor() as cur:
        cur.execute(sql_texto)
        return cur.fetchone()


def test_testes_rodam_no_postgresql():
    assert connection.vendor == "postgresql"


def test_testes_conectam_como_usuario_da_aplicacao():
    usuario, = consultar("select current_user")
    assert usuario == settings.DB_APP_USUARIO


def test_usuario_da_aplicacao_sem_poderes_extras():
    superusuario, bypassrls, cria_banco, cria_papel = consultar(
        "select rolsuper, rolbypassrls, rolcreatedb, rolcreaterole "
        "from pg_roles where rolname = current_user"
    )
    assert (superusuario, bypassrls, cria_banco, cria_papel) == (False, False, False, False)


def test_usuario_da_aplicacao_nao_e_dono_das_tabelas():
    donos_app, = consultar(
        "select count(*) from pg_tables where schemaname = 'public' and tableowner = current_user"
    )
    assert donos_app == 0


def test_usuario_da_aplicacao_nao_altera_o_historico_de_migracoes():
    with pytest.raises(Exception), transaction.atomic():
        consultar("delete from django_migrations returning id")


def test_idioma_e_fuso():
    assert settings.LANGUAGE_CODE == "pt-br"
    assert settings.TIME_ZONE == "America/Sao_Paulo"


def test_login_por_email_sem_diferenciar_maiusculas():
    get_user_model().objects.create_user("Ana@Exemplo.com", "senha-bem-longa-123")
    assert authenticate(email="ana@exemplo.com", password="senha-bem-longa-123") is not None
    assert authenticate(email="ANA@EXEMPLO.COM", password="senha-bem-longa-123") is not None
    assert authenticate(email="ana@exemplo.com", password="errada") is None


def test_email_unico_sem_diferenciar_maiusculas():
    Usuario = get_user_model()
    Usuario.objects.create_user("bia@exemplo.com", "senha-bem-longa-123")
    with pytest.raises(IntegrityError), transaction.atomic():
        Usuario.objects.create(email="BIA@exemplo.com")


def test_senha_curta_e_recusada():
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        validate_password("curta12345")
