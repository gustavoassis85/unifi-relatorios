"""Chave da UniFi de cada cliente: telas, papéis, isolamento, auditoria e cofre."""
import pytest
from cryptography.fernet import Fernet
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.urls import reverse

from auditoria.models import Acao, EventoOrganizacao
from clientes.models import Cliente
from conexoes.models import ChaveUniFi
from organizacoes.isolamento import contexto

pytestmark = pytest.mark.django_db

CHAVE_A = "chaveDoClienteA-0123456789-abcd"
CHAVE_A2 = "outraChaveDoA-9876543210-efgh"
CHAVE_B = "chaveDoClienteB-0123456789-wxyz"


def sql(texto, parametros=None):
    with connection.cursor() as cur:
        cur.execute(texto, parametros or [])
        return cur.fetchall() if cur.description else cur.rowcount


def criar_chave(org, cliente, texto):
    with contexto(organizacao_id=org.pk):
        chave = ChaveUniFi(cliente=cliente)
        chave.definir(texto)
        chave.save()
        return chave


def chave_de(org, cliente):
    with contexto(organizacao_id=org.pk):
        return ChaveUniFi.objects.filter(cliente=cliente).first()


def eventos(org, acao):
    with contexto(organizacao_id=org.pk):
        return list(EventoOrganizacao.objects.filter(acao=acao))


@pytest.fixture
def com_chave_b(msps):
    criar_chave(msps.org_b, msps.cliente_b, CHAVE_B)
    return msps


def url(nome, cliente):
    return reverse(nome, args=[cliente.pk])


# Cadastro, troca e exclusão -------------------------------------------------

def test_admin_cadastra_a_chave_cifrada(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    resposta = client.post(url("conexoes:chave", msps.cliente_a), {"chave": CHAVE_A})
    assert resposta.status_code == 302
    assert resposta["Location"] == url("clientes:detalhe", msps.cliente_a)

    chave = chave_de(msps.org_a, msps.cliente_a)
    assert chave.final == "abcd"
    assert CHAVE_A not in chave.chave_cifrada
    with contexto(organizacao_id=msps.org_a.pk):
        assert chave.abrir() == CHAVE_A
        coluna = sql("select chave_cifrada from conexoes_chaveunifi")[0][0]
    assert CHAVE_A not in coluna

    (evento,) = eventos(msps.org_a, Acao.CHAVE_CADASTRADA)
    assert evento.usuario == msps.admin_a
    assert evento.detalhes == {"cliente_id": msps.cliente_a.pk, "cliente": "Padaria do A", "final": "abcd"}


def test_chave_nunca_aparece_nas_telas(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    paginas = [client.post(url("conexoes:chave", msps.cliente_a), {"chave": CHAVE_A}, follow=True)]
    paginas += [
        client.get(url("clientes:detalhe", msps.cliente_a)),
        client.get(url("conexoes:chave", msps.cliente_a)),
        client.get(url("conexoes:chave_apagar", msps.cliente_a)),
        client.get(url("clientes:apagar", msps.cliente_a)),
        client.get(reverse("clientes:lista")),
    ]
    for pagina in paginas:
        html = pagina.content.decode()
        assert pagina.status_code == 200
        assert CHAVE_A not in html
        assert chave_de(msps.org_a, msps.cliente_a).chave_cifrada not in html
    assert "abcd" in paginas[1].content.decode()


def test_chave_invalida_nao_volta_para_a_tela(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    digitada = "chave com espaco e-coisa-estranha-<script>"
    resposta = client.post(url("conexoes:chave", msps.cliente_a), {"chave": digitada})
    html = resposta.content.decode()
    assert resposta.status_code == 200
    assert "Isso não parece uma chave da UniFi" in html
    assert "coisa-estranha" not in html
    assert chave_de(msps.org_a, msps.cliente_a) is None


def test_chave_valida_tambem_nao_volta_quando_o_formulario_reaparece(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    resposta = client.post(url("conexoes:chave", msps.cliente_a), {"chave": "curta"})
    assert 'value="curta"' not in resposta.content.decode()


def test_admin_troca_a_chave(msps, entrar_como):
    criar_chave(msps.org_a, msps.cliente_a, CHAVE_A)
    client = entrar_como(msps.admin_a)
    assert "termina em" in client.get(url("conexoes:chave", msps.cliente_a)).content.decode()
    client.post(url("conexoes:chave", msps.cliente_a), {"chave": CHAVE_A2})

    chave = chave_de(msps.org_a, msps.cliente_a)
    assert chave.final == "efgh"
    assert chave.trocada_em is not None
    with contexto(organizacao_id=msps.org_a.pk):
        assert chave.abrir() == CHAVE_A2
        assert ChaveUniFi.objects.count() == 1
    (evento,) = eventos(msps.org_a, Acao.CHAVE_TROCADA)
    assert evento.detalhes["final"] == "efgh"


def test_admin_apaga_a_chave(msps, entrar_como):
    criar_chave(msps.org_a, msps.cliente_a, CHAVE_A)
    client = entrar_como(msps.admin_a)
    confirmacao = client.get(url("conexoes:chave_apagar", msps.cliente_a)).content.decode()
    assert "Apagar a chave de Padaria do A" in confirmacao
    client.post(url("conexoes:chave_apagar", msps.cliente_a))
    assert chave_de(msps.org_a, msps.cliente_a) is None
    (evento,) = eventos(msps.org_a, Acao.CHAVE_APAGADA)
    assert evento.detalhes["final"] == "abcd"


def test_apagar_cliente_apaga_a_chave(msps, entrar_como):
    criar_chave(msps.org_a, msps.cliente_a, CHAVE_A)
    client = entrar_como(msps.admin_a)
    assert "A chave da UniFi dele também será apagada" in client.get(
        url("clientes:apagar", msps.cliente_a)
    ).content.decode()
    client.post(url("clientes:apagar", msps.cliente_a))
    with contexto(organizacao_id=msps.org_a.pk):
        assert not ChaveUniFi.objects.exists()
    (evento,) = eventos(msps.org_a, Acao.CLIENTE_APAGADO)
    assert evento.detalhes["conexao_unifi"] is True


def test_auditoria_nunca_guarda_a_chave(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    client.post(url("conexoes:chave", msps.cliente_a), {"chave": CHAVE_A})
    client.post(url("conexoes:chave", msps.cliente_a), {"chave": CHAVE_A2})
    client.post(url("conexoes:chave_apagar", msps.cliente_a))
    with contexto(organizacao_id=msps.org_a.pk):
        texto = str(list(EventoOrganizacao.objects.values_list("detalhes", flat=True)))
    assert CHAVE_A not in texto and CHAVE_A2 not in texto


# Papéis ----------------------------------------------------------------------

@pytest.mark.parametrize("quem", ["operador_a", "leitor_a"])
def test_so_admin_mexe_na_chave(msps, entrar_como, quem):
    criar_chave(msps.org_a, msps.cliente_a, CHAVE_A)
    client = entrar_como(getattr(msps, quem))
    assert client.get(url("conexoes:chave", msps.cliente_a)).status_code == 403
    assert client.post(url("conexoes:chave", msps.cliente_a), {"chave": CHAVE_A2}).status_code == 403
    assert client.post(url("conexoes:chave_apagar", msps.cliente_a)).status_code == 403
    with contexto(organizacao_id=msps.org_a.pk):
        assert chave_de(msps.org_a, msps.cliente_a).abrir() == CHAVE_A

    detalhe = client.get(url("clientes:detalhe", msps.cliente_a))
    assert detalhe.status_code == 200
    html = detalhe.content.decode()
    assert "abcd" in html
    assert "Trocar chave" not in html and "Apagar chave" not in html


# Isolamento pela tela ----------------------------------------------------------

def test_admin_de_a_nao_alcanca_chave_de_b(com_chave_b, entrar_como):
    msps = com_chave_b
    client = entrar_como(msps.admin_a)
    assert client.get(url("clientes:detalhe", msps.cliente_b)).status_code == 404
    assert client.get(url("conexoes:chave", msps.cliente_b)).status_code == 404
    assert client.post(url("conexoes:chave", msps.cliente_b), {"chave": CHAVE_A}).status_code == 404
    assert client.get(url("conexoes:chave_apagar", msps.cliente_b)).status_code == 404
    assert client.post(url("conexoes:chave_apagar", msps.cliente_b)).status_code == 404
    with contexto(organizacao_id=msps.org_b.pk):
        assert chave_de(msps.org_b, msps.cliente_b).abrir() == CHAVE_B
    assert eventos(msps.org_b, Acao.CHAVE_TROCADA) == []


# Isolamento no banco -----------------------------------------------------------

def test_rls_ligada_e_forcada():
    assert sql(
        "select relrowsecurity, relforcerowsecurity from pg_class where relname = 'conexoes_chaveunifi'"
    ) == [(True, True)]


def test_sql_direto_so_ve_a_propria_organizacao(com_chave_b):
    msps = com_chave_b
    criar_chave(msps.org_a, msps.cliente_a, CHAVE_A)
    with contexto(organizacao_id=msps.org_a.pk):
        linhas = sql("select organizacao_id, final from conexoes_chaveunifi")
        assert linhas == [(msps.org_a.pk, "abcd")]
        assert sql("select count(*) from conexoes_chaveunifi where organizacao_id = %s", [msps.org_b.pk]) == [(0,)]


def test_sem_organizacao_nada_aparece(com_chave_b):
    assert sql("select count(*) from conexoes_chaveunifi") == [(0,)]
    assert list(ChaveUniFi.objects.all()) == []


def test_banco_recusa_chave_em_cliente_de_outra_organizacao(msps):
    inserir = (
        "insert into conexoes_chaveunifi "
        "(organizacao_id, cliente_id, chave_cifrada, final, cadastrada_em, teste_resultado) "
        "values (%s, %s, 'x', 'x', now(), '')"
    )
    with contexto(organizacao_id=msps.org_a.pk):
        with pytest.raises(DatabaseError) as erro, transaction.atomic():
            sql(inserir, [msps.org_a.pk, msps.cliente_b.pk])
            sql("set constraints all immediate")
        assert "cliente_mesma_org" in str(erro.value)
        # Controle: o mesmo SQL com o cliente da própria organização funciona.
        with transaction.atomic():
            sql(inserir, [msps.org_a.pk, msps.cliente_a.pk])
            sql("set constraints all immediate")


def test_banco_recusa_mover_chave_para_cliente_de_outra_organizacao(msps):
    criar_chave(msps.org_a, msps.cliente_a, CHAVE_A)
    with contexto(organizacao_id=msps.org_a.pk):
        with pytest.raises(DatabaseError), transaction.atomic():
            sql("update conexoes_chaveunifi set cliente_id = %s", [msps.cliente_b.pk])
            sql("set constraints all immediate")


def test_aplicacao_recusa_chave_em_cliente_de_outra_organizacao(msps):
    from django.core.exceptions import PermissionDenied

    with contexto(organizacao_id=msps.org_a.pk):
        chave = ChaveUniFi(cliente=msps.cliente_b)
        chave.definir(CHAVE_A)
        with pytest.raises(PermissionDenied):
            chave.save()


# Troca da chave mestra com dados -----------------------------------------------

def test_recriptografar_regrava_as_chaves_de_todas_as_organizacoes(com_chave_b, settings):
    msps = com_chave_b
    criar_chave(msps.org_a, msps.cliente_a, CHAVE_A)
    antes_a = chave_de(msps.org_a, msps.cliente_a).chave_cifrada

    settings.UNIFI_CHAVES_MESTRAS_ANTERIORES = [settings.UNIFI_CHAVE_MESTRA]
    settings.UNIFI_CHAVE_MESTRA = Fernet.generate_key().decode()
    call_command("recriptografar")
    settings.UNIFI_CHAVES_MESTRAS_ANTERIORES = []  # fim da troca: só a nova

    depois_a = chave_de(msps.org_a, msps.cliente_a)
    assert depois_a.chave_cifrada != antes_a
    with contexto(organizacao_id=msps.org_a.pk):
        assert depois_a.abrir() == CHAVE_A
    with contexto(organizacao_id=msps.org_b.pk):
        assert chave_de(msps.org_b, msps.cliente_b).abrir() == CHAVE_B


def test_detalhe_abre_mesmo_com_chave_mestra_trocada_sem_recriptografar(msps, entrar_como, settings):
    # A tela não decifra a chave: mostra só o final guardado.
    criar_chave(msps.org_a, msps.cliente_a, CHAVE_A)
    settings.UNIFI_CHAVE_MESTRA = Fernet.generate_key().decode()
    resposta = entrar_como(msps.admin_a).get(url("clientes:detalhe", msps.cliente_a))
    assert resposta.status_code == 200
    assert "abcd" in resposta.content.decode()
