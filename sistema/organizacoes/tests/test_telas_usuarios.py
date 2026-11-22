import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apoio_testes import SENHA
from organizacoes.forms import EMAIL_RECUSADO
from organizacoes.isolamento import contexto
from organizacoes.models import Papel, Vinculo

pytestmark = pytest.mark.django_db

Usuario = get_user_model()


def papel_de(usuario, org):
    with contexto(organizacao_id=org.pk):
        return Vinculo.objects.get(usuario=usuario).papel


def novo_usuario(email, papel=Papel.LEITURA):
    return {
        "email": email,
        "nome": "Fulano",
        "papel": papel,
        "senha1": SENHA,
        "senha2": SENHA,
    }


# Isolamento pela tela: admin do MSP A não alcança usuário do MSP B (404)


def test_lista_mostra_so_usuarios_da_propria_organizacao(msps, entrar_como):
    resposta = entrar_como(msps.admin_a).get(reverse("usuarios:lista"))
    texto = resposta.content.decode()
    assert resposta.status_code == 200
    assert "admin@a.com" in texto and "op@a.com" in texto and "leitor@a.com" in texto
    assert "admin@b.com" not in texto


def test_admin_nao_abre_usuario_de_outra_organizacao(msps, entrar_como):
    resposta = entrar_como(msps.admin_a).get(reverse("usuarios:editar", args=[msps.admin_b.pk]))
    assert resposta.status_code == 404


def test_admin_nao_muda_papel_de_usuario_de_outra_organizacao(msps, entrar_como):
    resposta = entrar_como(msps.admin_a).post(
        reverse("usuarios:editar", args=[msps.admin_b.pk]),
        {"papel": Papel.LEITURA, "ativo": "on"},
    )
    assert resposta.status_code == 404
    assert papel_de(msps.admin_b, msps.org_b) == Papel.ADMIN


def test_admin_nao_desativa_usuario_de_outra_organizacao(msps, entrar_como):
    resposta = entrar_como(msps.admin_a).post(
        reverse("usuarios:editar", args=[msps.admin_b.pk]), {"papel": Papel.ADMIN}
    )
    assert resposta.status_code == 404
    msps.admin_b.refresh_from_db()
    assert msps.admin_b.is_active


def test_usuario_sem_vinculo_tambem_da_404(msps, entrar_como):
    solto = Usuario.objects.create_user("solto@x.com", SENHA)
    resposta = entrar_como(msps.admin_a).get(reverse("usuarios:editar", args=[solto.pk]))
    assert resposta.status_code == 404


# Cadastro


def test_admin_cadastra_usuario_na_propria_organizacao(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    resposta = client.post(reverse("usuarios:novo"), novo_usuario("novo@a.com", Papel.OPERADOR))
    assert resposta.status_code == 302
    novo = Usuario.objects.get(email="novo@a.com")
    assert papel_de(novo, msps.org_a) == Papel.OPERADOR
    assert not novo.is_staff and not novo.is_superuser


def test_email_de_outra_organizacao_da_mensagem_generica(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    resposta = client.post(reverse("usuarios:novo"), novo_usuario("ADMIN@b.com"))
    texto = resposta.content.decode()
    assert resposta.status_code == 200
    assert EMAIL_RECUSADO in texto
    assert "já existe" not in texto.lower()
    assert "MSP B" not in texto
    # O usuário do MSP B continua só no MSP B.
    assert papel_de(msps.admin_b, msps.org_b) == Papel.ADMIN
    with contexto(organizacao_id=msps.org_a.pk):
        assert not Vinculo.objects.filter(usuario=msps.admin_b).exists()


def test_email_de_outra_organizacao_e_da_propria_dao_a_mesma_resposta(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    de_outra = client.post(reverse("usuarios:novo"), novo_usuario("admin@b.com"))
    da_propria = client.post(reverse("usuarios:novo"), novo_usuario("op@a.com"))
    assert EMAIL_RECUSADO in de_outra.content.decode()
    assert EMAIL_RECUSADO in da_propria.content.decode()


def test_senha_curta_e_recusada(msps, entrar_como):
    dados = novo_usuario("curta@a.com")
    dados["senha1"] = dados["senha2"] = "curta123"
    entrar_como(msps.admin_a).post(reverse("usuarios:novo"), dados)
    assert not Usuario.objects.filter(email="curta@a.com").exists()


def test_nao_ha_como_criar_admin_do_django_pela_tela(msps, entrar_como):
    dados = novo_usuario("esperto@a.com")
    dados.update({"is_staff": "on", "is_superuser": "on"})
    entrar_como(msps.admin_a).post(reverse("usuarios:novo"), dados)
    esperto = Usuario.objects.get(email="esperto@a.com")
    assert not esperto.is_staff and not esperto.is_superuser


# Edição


def test_admin_muda_papel_e_desativa_usuario_da_propria_organizacao(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    client.post(reverse("usuarios:editar", args=[msps.leitor_a.pk]), {"papel": Papel.OPERADOR})
    msps.leitor_a.refresh_from_db()
    assert papel_de(msps.leitor_a, msps.org_a) == Papel.OPERADOR
    assert not msps.leitor_a.is_active


def test_usuario_desativado_perde_o_acesso(msps, entrar_como, client):
    entrar_como(msps.admin_a).post(
        reverse("usuarios:editar", args=[msps.leitor_a.pk]), {"papel": Papel.LEITURA}
    )
    client.logout()
    client.post(reverse("account_login"), {"login": "leitor@a.com", "password": SENHA})
    assert client.get(reverse("clientes:lista")).status_code == 302


def test_admin_nao_muda_o_proprio_papel_nem_se_desativa(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    url = reverse("usuarios:editar", args=[msps.admin_a.pk])
    client.post(url, {"papel": Papel.LEITURA, "ativo": "on"})
    client.post(url, {"papel": Papel.ADMIN})
    msps.admin_a.refresh_from_db()
    assert papel_de(msps.admin_a, msps.org_a) == Papel.ADMIN
    assert msps.admin_a.is_active


# Papéis


@pytest.mark.parametrize("quem", ["operador_a", "leitor_a"])
def test_so_admin_gerencia_usuarios(msps, entrar_como, quem):
    client = entrar_como(getattr(msps, quem))
    assert client.get(reverse("usuarios:lista")).status_code == 403
    assert client.get(reverse("usuarios:novo")).status_code == 403
    assert client.post(reverse("usuarios:novo"), novo_usuario("x@a.com")).status_code == 403
    url = reverse("usuarios:editar", args=[msps.leitor_a.pk])
    assert client.post(url, {"papel": Papel.ADMIN, "ativo": "on"}).status_code == 403
    assert papel_de(msps.leitor_a, msps.org_a) == Papel.LEITURA
    assert not Usuario.objects.filter(email="x@a.com").exists()


def test_operador_nao_ve_o_menu_de_usuarios(msps, entrar_como):
    resposta = entrar_como(msps.operador_a).get(reverse("clientes:lista"))
    assert reverse("usuarios:lista") not in resposta.content.decode()
