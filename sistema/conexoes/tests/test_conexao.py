"""Testar conexão e lista de consoles, com a UniFi simulada (nada vai para a internet)."""
import pytest
from cryptography.fernet import Fernet
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.urls import reverse

from auditoria.models import Acao, EventoOrganizacao
from clientes.models import Cliente
from conexoes import servicos
from conexoes.models import ChaveUniFi, Console
from organizacoes.isolamento import contexto
from unifi.api import ErroApi

pytestmark = pytest.mark.django_db

CHAVE_A = "chaveDoClienteA-0123456789-abcd"
CHAVE_B = "chaveDoClienteB-0123456789-wxyz"


def host(host_id, nome, conectado=True, **extra):
    return {
        "id": host_id,
        "type": "console",
        "userData": {"email": "dono@exemplo.com"},
        "reportedState": {
            "name": nome,
            "state": "connected" if conectado else "disconnected",
            "hardware": {"name": "UniFi Dream Router", "firmwareVersion": "4.3.6"},
            "controllers": [{"name": "network", "version": "10.5.67"}],
            "location": {"lat": -23.5},
            **extra,
        },
    }


UDR = host("udr:1", "UDR Lab")
ANTIGO = host("antigo:2", "Console antigo", conectado=False)


class UniFiFalsa:
    """Substitui a api.ui.com. Guarda as chaves usadas para conferir."""

    def __init__(self):
        self.hosts = [UDR, ANTIGO]
        self.erro = None
        self.chaves_usadas = []

    def __call__(self, chave_texto):
        self.chaves_usadas.append(chave_texto)
        return self

    def listar_hosts(self):
        if self.erro:
            raise self.erro
        return list(self.hosts)


@pytest.fixture
def unifi(monkeypatch):
    falsa = UniFiFalsa()
    monkeypatch.setattr(servicos, "criar_cliente_api", falsa)
    return falsa


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


def consoles_de(org, cliente):
    with contexto(organizacao_id=org.pk):
        return {c.host_id: c for c in Console.objects.filter(cliente=cliente)}


def chave_de(org, cliente):
    with contexto(organizacao_id=org.pk):
        return ChaveUniFi.objects.get(cliente=cliente)


def eventos_de_teste(org):
    with contexto(organizacao_id=org.pk):
        return list(EventoOrganizacao.objects.filter(acao=Acao.CONEXAO_TESTADA))


@pytest.fixture
def com_chaves(msps):
    criar_chave(msps.org_a, msps.cliente_a, CHAVE_A)
    criar_chave(msps.org_b, msps.cliente_b, CHAVE_B)
    return msps


def clicar_testar(client, cliente):
    return client.post(reverse("conexoes:testar", args=[cliente.pk]), follow=True)


# Teste que funciona -------------------------------------------------------------

@pytest.mark.parametrize("quem", ["admin_a", "operador_a"])
def test_testar_conexao_funciona_e_traz_os_consoles(com_chaves, entrar_como, unifi, quem):
    msps = com_chaves
    resposta = clicar_testar(entrar_como(getattr(msps, quem)), msps.cliente_a)
    html = resposta.content.decode()
    assert "Conexão funcionou: 2 console(s), 1 conectado(s)." in html
    assert "UDR Lab" in html and "Console antigo" in html
    assert unifi.chaves_usadas == [CHAVE_A]  # usou a chave do cliente certo, decifrada

    chave = chave_de(msps.org_a, msps.cliente_a)
    assert chave.teste_ok is True and chave.testada_em is not None

    consoles = consoles_de(msps.org_a, msps.cliente_a)
    assert set(consoles) == {"udr:1", "antigo:2"}
    assert consoles["udr:1"].acompanhar is True       # conectado: entra acompanhado
    assert consoles["antigo:2"].acompanhar is False   # desconectado: entra sem acompanhar
    assert consoles["udr:1"].modelo == "UniFi Dream Router"
    assert consoles["udr:1"].versao_network == "10.5.67"

    (evento,) = eventos_de_teste(msps.org_a)
    assert evento.detalhes == {
        "cliente_id": msps.cliente_a.pk, "cliente": "Padaria do A",
        "resultado": "ok", "consoles": 2, "conectados": 1,
    }


def test_conta_sem_consoles(com_chaves, entrar_como, unifi):
    unifi.hosts = []
    html = clicar_testar(entrar_como(com_chaves.admin_a), com_chaves.cliente_a).content.decode()
    assert "A chave funciona, mas a conta não tem nenhum console." in html


def test_dados_pessoais_do_hosts_nao_sao_guardados(com_chaves, entrar_como, unifi):
    clicar_testar(entrar_como(com_chaves.admin_a), com_chaves.cliente_a)
    with contexto(organizacao_id=com_chaves.org_a.pk):
        texto = str(list(Console.objects.values()))
    assert "dono@exemplo.com" not in texto and "-23.5" not in texto


# Erros --------------------------------------------------------------------------

@pytest.mark.parametrize("codigo,mensagem", [
    ("chave_recusada", "A UniFi recusou a chave (401)."),
    ("sem_permissao", "A chave não tem permissão para /v1/hosts (403)."),
    ("limite", "A UniFi pediu para esperar."),
    ("rede", "Falha de rede ao falar com a UniFi (ConnectionError)."),
    ("tempo", "A UniFi demorou demais para responder."),
])
def test_cada_erro_mostra_a_mensagem_certa(com_chaves, entrar_como, unifi, codigo, mensagem):
    unifi.erro = ErroApi(codigo, mensagem)
    html = clicar_testar(entrar_como(com_chaves.admin_a), com_chaves.cliente_a).content.decode()
    assert mensagem in html
    assert CHAVE_A not in html
    chave = chave_de(com_chaves.org_a, com_chaves.cliente_a)
    assert chave.teste_ok is False and chave.teste_resultado == mensagem
    assert consoles_de(com_chaves.org_a, com_chaves.cliente_a) == {}
    (evento,) = eventos_de_teste(com_chaves.org_a)
    assert evento.detalhes["resultado"] == codigo


def test_chave_mestra_errada_vira_mensagem_clara(com_chaves, entrar_como, unifi, settings):
    settings.UNIFI_CHAVE_MESTRA = Fernet.generate_key().decode()
    html = clicar_testar(entrar_como(com_chaves.admin_a), com_chaves.cliente_a).content.decode()
    assert "Não foi possível abrir a credencial guardada" in html
    assert unifi.chaves_usadas == []


def test_sem_chave_pede_para_cadastrar(msps, entrar_como, unifi):
    html = clicar_testar(entrar_como(msps.admin_a), msps.cliente_a).content.decode()
    assert "Cadastre a chave da UniFi antes de testar." in html
    assert unifi.chaves_usadas == []


def test_limite_de_5_testes_por_minuto_por_organizacao(com_chaves, entrar_como, unifi):
    client = entrar_como(com_chaves.admin_a)
    for _ in range(5):
        assert "Conexão funcionou" in clicar_testar(client, com_chaves.cliente_a).content.decode()
    html = clicar_testar(client, com_chaves.cliente_a).content.decode()
    assert "Muitos testes seguidos" in html
    assert len(unifi.chaves_usadas) == 5
    assert len(eventos_de_teste(com_chaves.org_a)) == 5
    # O limite é por organização: o MSP B continua podendo testar.
    assert "Conexão funcionou" in clicar_testar(entrar_como(com_chaves.admin_b), com_chaves.cliente_b).content.decode()


# Papéis -------------------------------------------------------------------------

def test_leitura_nao_testa_e_nao_ve_o_botao(com_chaves, entrar_como, unifi):
    client = entrar_como(com_chaves.leitor_a)
    assert client.post(reverse("conexoes:testar", args=[com_chaves.cliente_a.pk])).status_code == 403
    assert unifi.chaves_usadas == []
    html = client.get(reverse("clientes:detalhe", args=[com_chaves.cliente_a.pk])).content.decode()
    assert "Testar conexão" not in html


def test_testar_so_por_post(com_chaves, entrar_como, unifi):
    client = entrar_como(com_chaves.admin_a)
    assert client.get(reverse("conexoes:testar", args=[com_chaves.cliente_a.pk])).status_code == 405
    assert unifi.chaves_usadas == []


# Consoles ao longo dos testes -----------------------------------------------------

def test_console_que_some_fica_marcado_e_volta(com_chaves, entrar_como, unifi):
    client = entrar_como(com_chaves.admin_a)
    clicar_testar(client, com_chaves.cliente_a)

    unifi.hosts = [ANTIGO]
    html = clicar_testar(client, com_chaves.cliente_a).content.decode()
    assert "Não aparece mais na conta" in html
    udr = consoles_de(com_chaves.org_a, com_chaves.cliente_a)["udr:1"]
    assert udr.na_conta is False and udr.conectado is False
    assert udr.acompanhar is True  # a escolha do MSP não muda sozinha

    unifi.hosts = [host("udr:1", "UDR Lab renomeado"), ANTIGO]
    clicar_testar(client, com_chaves.cliente_a)
    udr = consoles_de(com_chaves.org_a, com_chaves.cliente_a)["udr:1"]
    assert udr.na_conta is True and udr.nome == "UDR Lab renomeado"


def test_acompanhar_escolhido_nao_muda_com_novo_teste(com_chaves, entrar_como, unifi):
    client = entrar_como(com_chaves.admin_a)
    clicar_testar(client, com_chaves.cliente_a)
    with contexto(organizacao_id=com_chaves.org_a.pk):
        Console.objects.filter(host_id="udr:1").update(acompanhar=False)
    clicar_testar(client, com_chaves.cliente_a)
    assert consoles_de(com_chaves.org_a, com_chaves.cliente_a)["udr:1"].acompanhar is False


def test_mesmo_console_em_dois_clientes_da_organizacao_so_acompanha_no_primeiro(com_chaves, entrar_como, unifi):
    msps = com_chaves
    with contexto(organizacao_id=msps.org_a.pk):
        outro = Cliente.objects.create(nome="Filial do A")
    criar_chave(msps.org_a, outro, "mesmaContaEmOutroCliente-0000")
    client = entrar_como(msps.admin_a)
    clicar_testar(client, msps.cliente_a)
    clicar_testar(client, outro)
    assert consoles_de(msps.org_a, msps.cliente_a)["udr:1"].acompanhar is True
    assert consoles_de(msps.org_a, outro)["udr:1"].acompanhar is False

    # O banco também recusa os dois acompanhados ao mesmo tempo.
    with contexto(organizacao_id=msps.org_a.pk):
        with pytest.raises(IntegrityError), transaction.atomic():
            Console.objects.filter(cliente=outro, host_id="udr:1").update(acompanhar=True)


def test_mesmo_console_em_organizacoes_diferentes_nao_conflita(com_chaves, entrar_como, unifi):
    clicar_testar(entrar_como(com_chaves.admin_a), com_chaves.cliente_a)
    clicar_testar(entrar_como(com_chaves.admin_b), com_chaves.cliente_b)
    assert consoles_de(com_chaves.org_a, com_chaves.cliente_a)["udr:1"].acompanhar is True
    assert consoles_de(com_chaves.org_b, com_chaves.cliente_b)["udr:1"].acompanhar is True


# Isolamento ------------------------------------------------------------------------

def test_admin_de_a_nao_testa_cliente_de_b(com_chaves, entrar_como, unifi):
    resposta = entrar_como(com_chaves.admin_a).post(reverse("conexoes:testar", args=[com_chaves.cliente_b.pk]))
    assert resposta.status_code == 404
    assert unifi.chaves_usadas == []
    assert chave_de(com_chaves.org_b, com_chaves.cliente_b).testada_em is None


def test_consoles_de_b_nao_aparecem_para_a(com_chaves, entrar_como, unifi):
    unifi.hosts = [host("so-do-b:9", "Console da Escola")]
    clicar_testar(entrar_como(com_chaves.admin_b), com_chaves.cliente_b)
    html = entrar_como(com_chaves.admin_a).get(
        reverse("clientes:detalhe", args=[com_chaves.cliente_a.pk])
    ).content.decode()
    assert "Console da Escola" not in html
    with contexto(organizacao_id=com_chaves.org_a.pk):
        assert sql("select count(*) from conexoes_console") == [(0,)]
        assert not Console.objects.filter(host_id="so-do-b:9").exists()
    assert sql("select count(*) from conexoes_console") == [(0,)]  # sem organização


def test_rls_ligada_e_forcada_em_consoles():
    assert sql(
        "select relrowsecurity, relforcerowsecurity from pg_class where relname = 'conexoes_console'"
    ) == [(True, True)]


def test_banco_recusa_console_em_cliente_de_outra_organizacao(msps):
    inserir = (
        "insert into conexoes_console (organizacao_id, cliente_id, host_id, nome, modelo, tipo, "
        "conectado, firmware, versao_network, acompanhar, na_conta, primeiro_visto_em, visto_em) "
        "values (%s, %s, 'x:1', '', '', '', false, '', '', false, true, now(), now())"
    )
    with contexto(organizacao_id=msps.org_a.pk):
        with pytest.raises(DatabaseError) as erro, transaction.atomic():
            sql(inserir, [msps.org_a.pk, msps.cliente_b.pk])
            sql("set constraints all immediate")
        assert "cliente_mesma_org" in str(erro.value)
        with transaction.atomic():  # controle: com o cliente da própria organização, funciona
            sql(inserir, [msps.org_a.pk, msps.cliente_a.pk])
            sql("set constraints all immediate")


# Revisão de segurança --------------------------------------------------------------

def test_nome_vindo_da_unifi_nao_vira_codigo_na_pagina(com_chaves, entrar_como, unifi):
    unifi.hosts = [host("xss:1", '<script>alert("x")</script>')]
    html = clicar_testar(entrar_como(com_chaves.admin_a), com_chaves.cliente_a).content.decode()
    assert '<script>alert("x")</script>' not in html
    assert "&lt;script&gt;" in html


def test_apagar_cliente_apaga_consoles_so_dele(com_chaves, entrar_como, unifi):
    clicar_testar(entrar_como(com_chaves.admin_a), com_chaves.cliente_a)
    clicar_testar(entrar_como(com_chaves.admin_b), com_chaves.cliente_b)
    entrar_como(com_chaves.admin_a).post(reverse("clientes:apagar", args=[com_chaves.cliente_a.pk]))
    with contexto(organizacao_id=com_chaves.org_a.pk):
        assert not Console.objects.exists()
        assert not ChaveUniFi.objects.exists()
    assert len(consoles_de(com_chaves.org_b, com_chaves.cliente_b)) == 2
    assert chave_de(com_chaves.org_b, com_chaves.cliente_b) is not None
