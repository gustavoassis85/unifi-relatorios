"""Isolamento entre MSPs no banco. Todos os testes rodam como o usuário da aplicação
(unifi_app), sem ser dono das tabelas, sem superusuário e sem BYPASSRLS."""
import pytest
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, connection, transaction
from django.http import HttpResponse, HttpResponseServerError
from django.test import RequestFactory

from apoio_testes import SENHA
from clientes.models import Cliente
from organizacoes.isolamento import (
    CHAVE_ORGANIZACAO,
    CHAVE_USUARIO,
    SemOrganizacao,
    contexto,
    organizacao_atual,
)
from organizacoes.middleware import ContextoOrganizacaoMiddleware
from organizacoes.models import Papel, Vinculo
from organizacoes.servicos import (
    criar_organizacao_com_admin,
    criar_usuario_na_organizacao,
    vinculos_da_organizacao,
)

pytestmark = pytest.mark.django_db


def sql(texto, parametros=None):
    """SQL direto, sem passar pela camada de isolamento do Django."""
    with connection.cursor() as cur:
        cur.execute(texto, parametros or [])
        return cur.fetchall() if cur.description else cur.rowcount


def configuracao(chave):
    return sql("select current_setting(%s, true)", [chave])[0][0] or ""


@pytest.fixture
def dois_msps():
    org_a, admin_a = criar_organizacao_com_admin("MSP A", "admin@a.com", "Ana", SENHA)
    org_b, admin_b = criar_organizacao_com_admin("MSP B", "admin@b.com", "Bia", SENHA)
    with contexto(organizacao_id=org_a.pk):
        Cliente.objects.create(nome="Padaria do A")
        Cliente.objects.create(nome="Farmácia do A")
        criar_usuario_na_organizacao(org_a, "leitor@a.com", "Leo", SENHA, Papel.LEITURA)
    with contexto(organizacao_id=org_b.pk):
        Cliente.objects.create(nome="Escola do B")
    return org_a, admin_a, org_b, admin_b


# A trava do banco está ligada


@pytest.mark.parametrize("tabela", ["clientes_cliente", "organizacoes_vinculo"])
def test_rls_ligada_e_forcada(tabela):
    ligada, forcada = sql(
        "select relrowsecurity, relforcerowsecurity from pg_class where relname = %s", [tabela]
    )[0]
    assert ligada and forcada


def test_conectado_como_usuario_da_aplicacao():
    assert sql("select current_user")[0][0] == settings.DB_APP_USUARIO


# Leitura


def test_sql_direto_com_organizacao_a_so_devolve_linhas_de_a(dois_msps):
    org_a, *_ = dois_msps
    with contexto(organizacao_id=org_a.pk):
        nomes = {linha[0] for linha in sql("select nome from clientes_cliente")}
        orgs = {linha[0] for linha in sql("select organizacao_id from clientes_cliente")}
    assert nomes == {"Padaria do A", "Farmácia do A"}
    assert orgs == {org_a.pk}


def test_sql_direto_mesmo_filtrando_por_b_nao_ve_b(dois_msps):
    org_a, _, org_b, _ = dois_msps
    with contexto(organizacao_id=org_a.pk):
        linhas = sql("select nome from clientes_cliente where organizacao_id = %s", [org_b.pk])
    assert linhas == []


def test_sem_organizacao_definida_nada_aparece(dois_msps):
    assert sql("select count(*) from clientes_cliente")[0][0] == 0
    assert sql("select count(*) from organizacoes_vinculo")[0][0] == 0


def test_vinculo_com_so_o_usuario_definido_mostra_so_o_proprio(dois_msps):
    _, admin_a, _, _ = dois_msps
    with contexto(usuario_id=admin_a.pk):
        linhas = sql("select usuario_id from organizacoes_vinculo")
    assert linhas == [(admin_a.pk,)]


def test_vinculos_com_organizacao_a_nao_mostram_os_de_b(dois_msps):
    org_a, admin_a, org_b, admin_b = dois_msps
    with contexto(organizacao_id=org_a.pk, usuario_id=admin_a.pk):
        orgs = {linha[0] for linha in sql("select organizacao_id from organizacoes_vinculo")}
        emails = {v.usuario.email for v in vinculos_da_organizacao()}
    assert orgs == {org_a.pk}
    assert emails == {"admin@a.com", "leitor@a.com"}


# Escrita


def test_banco_recusa_cliente_com_id_de_outra_organizacao(dois_msps):
    org_a, _, org_b, _ = dois_msps
    with contexto(organizacao_id=org_a.pk):
        with pytest.raises(DatabaseError), transaction.atomic():
            sql(
                "insert into clientes_cliente (nome, criado_em, organizacao_id) "
                "values ('Intruso', now(), %s)",
                [org_b.pk],
            )
        # Pelo Django, pulando o save() (que já recusaria): o banco recusa do mesmo jeito.
        with pytest.raises(DatabaseError), transaction.atomic():
            Cliente.objects.bulk_create([Cliente(nome="Intruso", organizacao_id=org_b.pk)])
    with contexto(organizacao_id=org_b.pk):
        assert not Cliente.objects.filter(nome="Intruso").exists()


def test_banco_recusa_mover_cliente_para_outra_organizacao(dois_msps):
    org_a, _, org_b, _ = dois_msps
    with contexto(organizacao_id=org_a.pk):
        with pytest.raises(DatabaseError), transaction.atomic():
            sql("update clientes_cliente set organizacao_id = %s", [org_b.pk])


def test_alterar_ou_apagar_linhas_de_b_nao_afeta_nada(dois_msps):
    org_a, _, org_b, _ = dois_msps
    with contexto(organizacao_id=org_a.pk):
        assert sql("update clientes_cliente set nome = 'X' where organizacao_id = %s", [org_b.pk]) == 0
        assert sql("delete from clientes_cliente where organizacao_id = %s", [org_b.pk]) == 0
    with contexto(organizacao_id=org_b.pk):
        assert list(Cliente.objects.values_list("nome", flat=True)) == ["Escola do B"]


def test_sem_organizacao_o_banco_recusa_gravar(dois_msps):
    org_a, *_ = dois_msps
    with pytest.raises(DatabaseError), transaction.atomic():
        sql(
            "insert into clientes_cliente (nome, criado_em, organizacao_id) "
            "values ('Sem dono', now(), %s)",
            [org_a.pk],
        )


def test_banco_recusa_vinculo_em_outra_organizacao(dois_msps):
    org_a, _, org_b, _ = dois_msps
    from django.contrib.auth import get_user_model

    novo = get_user_model().objects.create_user("novo@x.com", SENHA)
    with contexto(organizacao_id=org_a.pk):
        with pytest.raises(DatabaseError), transaction.atomic():
            Vinculo.objects.create(usuario=novo, organizacao=org_b, papel=Papel.ADMIN)


def test_usuario_nao_muda_o_proprio_vinculo_so_com_o_usuario_definido(dois_msps):
    _, admin_a, _, _ = dois_msps
    with contexto(usuario_id=admin_a.pk):
        alteradas = sql(
            "update organizacoes_vinculo set papel = 'leitura' where usuario_id = %s", [admin_a.pk]
        )
    assert alteradas == 0


# Camada de isolamento do Django


def test_camada_sem_organizacao_devolve_nada_e_nao_grava(dois_msps):
    assert list(Cliente.objects.all()) == []
    with pytest.raises(SemOrganizacao):
        Cliente(nome="Sem organização").save()


def test_camada_filtra_pela_organizacao_atual(dois_msps):
    org_a, *_ = dois_msps
    with contexto(organizacao_id=org_a.pk):
        assert set(Cliente.objects.values_list("nome", flat=True)) == {
            "Padaria do A",
            "Farmácia do A",
        }


def test_camada_recusa_gravar_em_outra_organizacao(dois_msps):
    org_a, _, org_b, _ = dois_msps
    with contexto(organizacao_id=org_a.pk):
        with pytest.raises(PermissionDenied):
            Cliente(nome="Intruso", organizacao_id=org_b.pk).save()


def test_admin_nao_cria_usuario_em_outra_organizacao(dois_msps):
    org_a, _, org_b, _ = dois_msps
    with contexto(organizacao_id=org_a.pk):
        with pytest.raises(PermissionDenied):
            criar_usuario_na_organizacao(org_b, "x@b.com", "X", SENHA, Papel.ADMIN)


def test_contexto_so_aceita_numero():
    # O valor vai como parâmetro e precisa ser número: texto malicioso nem chega ao banco.
    with pytest.raises(ValueError):
        with contexto(organizacao_id="1; drop table clientes_cliente"):
            pass


def test_contexto_e_restaurado_ao_sair(dois_msps):
    org_a, *_ = dois_msps
    with contexto(organizacao_id=org_a.pk):
        assert configuracao(CHAVE_ORGANIZACAO) == str(org_a.pk)
    assert configuracao(CHAVE_ORGANIZACAO) == ""
    assert organizacao_atual() is None


def test_criar_organizacao_nao_deixa_o_dono_com_organizacao_definida():
    criar_organizacao_com_admin("MSP C", "admin@c.com", "Caio", SENHA)
    assert configuracao(CHAVE_ORGANIZACAO) == ""
    assert organizacao_atual() is None


# Middleware: organização da requisição


def chamar_middleware(usuario, visao):
    requisicao = RequestFactory().get("/")
    requisicao.user = usuario
    return requisicao, ContextoOrganizacaoMiddleware(visao)(requisicao)


def test_middleware_define_a_organizacao_do_usuario_logado(dois_msps):
    org_a, admin_a, _, _ = dois_msps
    visto = {}

    def visao(requisicao):
        visto["nomes"] = {linha[0] for linha in sql("select nome from clientes_cliente")}
        visto["usuario"] = configuracao(CHAVE_USUARIO)
        return HttpResponse("ok")

    requisicao, _ = chamar_middleware(admin_a, visao)
    assert visto["nomes"] == {"Padaria do A", "Farmácia do A"}
    assert visto["usuario"] == str(admin_a.pk)
    assert requisicao.vinculo.organizacao_id == org_a.pk
    # Fora da requisição, nada fica definido na conexão.
    assert configuracao(CHAVE_ORGANIZACAO) == ""
    assert configuracao(CHAVE_USUARIO) == ""


def test_middleware_sem_login_nao_define_organizacao(dois_msps):
    visto = {}

    def visao(requisicao):
        visto["total"] = sql("select count(*) from clientes_cliente")[0][0]
        return HttpResponse("ok")

    chamar_middleware(AnonymousUser(), visao)
    assert visto["total"] == 0


def test_middleware_dono_da_plataforma_nao_ve_clientes(dois_msps):
    from django.contrib.auth import get_user_model

    dono = get_user_model().objects.create_superuser("dono@plataforma.com", SENHA)
    visto = {}

    def visao(requisicao):
        visto["total"] = sql("select count(*) from clientes_cliente")[0][0]
        return HttpResponse("ok")

    requisicao, _ = chamar_middleware(dono, visao)
    assert visto["total"] == 0
    assert requisicao.vinculo is None


def test_middleware_organizacao_inativa_fica_sem_acesso(dois_msps):
    org_a, admin_a, _, _ = dois_msps
    org_a.ativa = False
    org_a.save()
    visto = {}

    def visao(requisicao):
        visto["total"] = sql("select count(*) from clientes_cliente")[0][0]
        return HttpResponse("ok")

    requisicao, _ = chamar_middleware(admin_a, visao)
    assert visto["total"] == 0
    assert requisicao.vinculo is None


def test_middleware_erro_500_desfaz_o_que_a_requisicao_gravou(dois_msps):
    org_a, admin_a, _, _ = dois_msps

    def visao(requisicao):
        Cliente.objects.create(nome="Gravado antes do erro")
        return HttpResponseServerError("erro")

    chamar_middleware(admin_a, visao)
    with contexto(organizacao_id=org_a.pk):
        assert not Cliente.objects.filter(nome="Gravado antes do erro").exists()
