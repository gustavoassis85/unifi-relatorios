import pytest
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apoio_testes import SENHA, ativar_mfa
from organizacoes import papeis
from organizacoes.isolamento import contexto
from organizacoes.models import Organizacao, Papel, Vinculo
from organizacoes.servicos import criar_organizacao_com_admin, vincular

pytestmark = pytest.mark.django_db

URL_ADMIN = "/" + settings.ADMIN_URL


@pytest.fixture
def dono_plataforma():
    dono = get_user_model().objects.create_superuser("dono@plataforma.com", SENHA)
    ativar_mfa(dono)
    return dono


def test_cria_organizacao_com_primeiro_admin():
    org, usuario = criar_organizacao_com_admin("MSP A", "Admin@MspA.com", "Ana", SENHA)
    assert usuario.email == "admin@mspa.com"
    assert usuario.vinculo.organizacao == org
    assert usuario.vinculo.papel == Papel.ADMIN
    assert not usuario.is_staff and not usuario.is_superuser
    assert authenticate(email="admin@mspa.com", password=SENHA) == usuario


def test_falha_no_meio_nao_deixa_organizacao_sem_admin(dono_plataforma):
    # E-mail já usado pelo dono: a criação do usuário falha e a organização não fica criada.
    with pytest.raises(IntegrityError):
        criar_organizacao_com_admin("MSP X", "dono@plataforma.com", "X", SENHA)
    assert not Organizacao.objects.filter(nome="MSP X").exists()


def test_nome_de_organizacao_unico_sem_diferenciar_maiusculas():
    Organizacao.objects.create(nome="MSP A")
    with pytest.raises(IntegrityError), transaction.atomic():
        Organizacao.objects.create(nome="msp a")


def test_usuario_pertence_a_uma_so_organizacao():
    org_a, usuario = criar_organizacao_com_admin("MSP A", "a@a.com", "A", SENHA)
    org_b = Organizacao.objects.create(nome="MSP B")
    with pytest.raises(IntegrityError), contexto(organizacao_id=org_b.pk):
        Vinculo.objects.create(usuario=usuario, organizacao=org_b, papel=Papel.LEITURA)


def test_papel_invalido_e_recusado_pelo_banco():
    org = Organizacao.objects.create(nome="MSP A")
    usuario = get_user_model().objects.create_user("x@a.com", SENHA)
    with pytest.raises(IntegrityError), contexto(organizacao_id=org.pk):
        Vinculo.objects.create(usuario=usuario, organizacao=org, papel="superpoder")


def test_dono_da_plataforma_nao_pertence_a_organizacao(dono_plataforma):
    org = Organizacao.objects.create(nome="MSP A")
    with pytest.raises(ValidationError):
        vincular(dono_plataforma, org, Papel.ADMIN)


@pytest.mark.parametrize(
    "papel, ver, editar, usuarios, mfa",
    [
        (Papel.ADMIN, True, True, True, True),
        (Papel.OPERADOR, True, True, False, False),
        (Papel.LEITURA, True, False, False, False),
    ],
)
def test_matriz_de_permissoes(papel, ver, editar, usuarios, mfa):
    assert papeis.pode_ver_clientes(papel) is ver
    assert papeis.pode_editar_clientes(papel) is editar
    assert papeis.pode_gerenciar_usuarios(papel) is usuarios
    assert papeis.exige_mfa(papel) is mfa


def test_admin_do_django_nao_mostra_vinculos():
    assert admin.site.is_registered(Organizacao)
    assert not admin.site.is_registered(Vinculo)


def test_admin_nao_fica_em_barra_admin():
    assert settings.ADMIN_URL.strip("/") != "admin"


def test_dono_cria_organizacao_e_primeiro_admin_pelo_admin(client, dono_plataforma):
    client.force_login(dono_plataforma)
    resposta = client.post(
        URL_ADMIN + "organizacoes/organizacao/add/",
        {
            "nome": "MSP Novo",
            "admin_email": "chefe@novo.com",
            "admin_nome": "Chefe",
            "admin_senha1": SENHA,
            "admin_senha2": SENHA,
            "_save": "Salvar",
        },
    )
    assert resposta.status_code == 302
    org = Organizacao.objects.get(nome="MSP Novo")
    with contexto(organizacao_id=org.pk):
        vinculo = Vinculo.objects.get(usuario__email="chefe@novo.com")
    assert vinculo.organizacao == org and vinculo.papel == Papel.ADMIN


def test_admin_recusa_senha_curta_e_nao_cria_nada(client, dono_plataforma):
    client.force_login(dono_plataforma)
    resposta = client.post(
        URL_ADMIN + "organizacoes/organizacao/add/",
        {
            "nome": "MSP Curto",
            "admin_email": "c@curto.com",
            "admin_nome": "C",
            "admin_senha1": "curta123",
            "admin_senha2": "curta123",
            "_save": "Salvar",
        },
    )
    assert resposta.status_code == 200
    assert not Organizacao.objects.filter(nome="MSP Curto").exists()
    assert not get_user_model().objects.filter(email="c@curto.com").exists()


def test_admin_de_organizacao_nao_entra_no_admin_do_django(client):
    _, usuario = criar_organizacao_com_admin("MSP A", "a@a.com", "A", SENHA)
    ativar_mfa(usuario)
    client.force_login(usuario)
    resposta = client.get(URL_ADMIN, follow=True)
    # Vai parar na tela do sistema, nunca numa página do admin do Django.
    assert resposta.redirect_chain[-1][0] == "/clientes/"
    assert resposta.status_code == 200


def test_admin_do_django_nao_apaga_organizacao(client, dono_plataforma):
    org = Organizacao.objects.create(nome="MSP A")
    client.force_login(dono_plataforma)
    resposta = client.get(URL_ADMIN + f"organizacoes/organizacao/{org.pk}/delete/")
    assert resposta.status_code == 403
