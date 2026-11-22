"""Tarefa de coleta por cliente e agendamento de hora em hora (UniFi simulada)."""
import pytest
from django.db import DatabaseError, connection, transaction

from clientes.models import Cliente
from coletas import tarefas as coleta
from coletas.models import ExecucaoColeta
from conexoes.models import ChaveUniFi, Console
from organizacoes.isolamento import contexto
from tarefas.fila import executar, pegar_proxima
from tarefas.models import Situacao, Tarefa
from unifi.api import ErroApi

pytestmark = pytest.mark.django_db

CHAVE_A = "chaveDoClienteA-0123456789-abcd"
CHAVE_B = "chaveDoClienteB-0123456789-wxyz"


def sql(texto, parametros=None):
    with connection.cursor() as cur:
        cur.execute(texto, parametros or [])
        return cur.fetchall() if cur.description else cur.rowcount


def preparar(org, cliente, chave=None, consoles=(("udr:1", True),)):
    with contexto(organizacao_id=org.pk):
        if chave:
            c = ChaveUniFi(cliente=cliente)
            c.definir(chave)
            c.save()
        for host_id, acompanhar in consoles:
            Console.objects.create(cliente=cliente, host_id=host_id, nome=host_id, acompanhar=acompanhar)


@pytest.fixture
def cenario(msps):
    preparar(msps.org_a, msps.cliente_a, CHAVE_A, [("udr:1", True), ("velho:2", False)])
    preparar(msps.org_b, msps.cliente_b, CHAVE_B)
    with contexto(organizacao_id=msps.org_a.pk):
        msps.sem_chave = Cliente.objects.create(nome="Sem chave")
        msps.sem_console = Cliente.objects.create(nome="Sem console acompanhado")
    preparar(msps.org_a, msps.sem_chave, None, [("outro:3", True)])
    preparar(msps.org_a, msps.sem_console, "chaveSemConsole-0123456789-0000", [("x:9", False)])
    return msps


@pytest.fixture
def unifi(monkeypatch):
    chaves = []
    monkeypatch.setattr(coleta, "criar_cliente_api", lambda texto: chaves.append(texto) or object())
    return chaves


@pytest.fixture
def partes(monkeypatch):
    """Troca as partes da coleta pelas do teste."""
    lista = []
    monkeypatch.setattr(coleta, "_partes", lista)

    def definir(*itens):
        lista[:] = [(i, nome, funcao) for i, (nome, funcao) in enumerate(itens)]

    return definir


def execucoes(org):
    with contexto(organizacao_id=org.pk):
        return list(ExecucaoColeta.objects.all())


def rodar(org, cliente, **extra):
    t = coleta.enfileirar_coleta(org.pk, cliente.pk, **extra)
    executar(pegar_proxima())
    return Tarefa.objects.get(pk=t.pk)


# Agendamento ------------------------------------------------------------------------

def test_so_clientes_com_chave_e_console_acompanhado(cenario):
    assert coleta.clientes_para_coletar(cenario.org_a.pk) == [cenario.cliente_a.pk]
    assert coleta.clientes_para_coletar(cenario.org_b.pk) == [cenario.cliente_b.pk]


def test_agenda_uma_por_cliente_de_todas_as_organizacoes_sem_duplicar(cenario):
    assert coleta.agendar_coletas(None) == 2
    assert coleta.agendar_coletas(None) == 0
    tarefas = {(t.organizacao_id, t.cliente_id) for t in Tarefa.objects.filter(situacao=Situacao.FILA)}
    assert tarefas == {(cenario.org_a.pk, cenario.cliente_a.pk), (cenario.org_b.pk, cenario.cliente_b.pk)}


def test_organizacao_inativa_nao_e_coletada(cenario):
    cenario.org_b.ativa = False
    cenario.org_b.save()
    assert coleta.agendar_coletas(None) == 1


# Execução ---------------------------------------------------------------------------

def test_coleta_usa_a_chave_do_cliente_certo_e_so_consoles_acompanhados(cenario, unifi, partes):
    recebidos = []
    partes(("Consoles", lambda ctx: recebidos.append([c.host_id for c in ctx.consoles]) or "1 console"))
    t = rodar(cenario.org_a, cenario.cliente_a)
    assert t.situacao == Situacao.FEITA
    assert unifi == [CHAVE_A]
    assert recebidos == [["udr:1"]]
    (execucao,) = execucoes(cenario.org_a)
    assert execucao.resultado == "ok" and execucao.automatica is True and execucao.terminada_em
    assert execucao.partes == [{"nome": "Consoles", "ok": True, "mensagem": "1 console"}]


def test_uma_parte_com_falha_nao_derruba_as_outras(cenario, unifi, partes):
    def falha(ctx):
        raise ErroApi("rede", "Falha de rede ao falar com a UniFi (ConnectionError).")

    def quebra(ctx):
        raise KeyError("segredo-interno")

    partes(("WAN", falha), ("Equipamentos", quebra), ("Clientes", lambda ctx: "5 clientes"))
    t = rodar(cenario.org_a, cenario.cliente_a)
    assert t.situacao == Situacao.FEITA
    (execucao,) = execucoes(cenario.org_a)
    assert execucao.resultado == "parcial"
    assert [p["ok"] for p in execucao.partes] == [False, False, True]
    assert execucao.partes[1]["mensagem"] == "Erro inesperado (KeyError)."
    assert "segredo-interno" not in str(execucao.partes)


def test_tudo_falhando_por_rede_tenta_de_novo_mais_tarde(cenario, unifi, partes):
    def falha(ctx):
        raise ErroApi("tempo", "A UniFi demorou demais para responder.")

    partes(("Consoles", falha), ("WAN", falha))
    t = rodar(cenario.org_a, cenario.cliente_a)
    assert t.situacao == Situacao.FILA and t.erro == "A UniFi demorou demais para responder."
    assert execucoes(cenario.org_a)[0].resultado == "falhou"


def test_chave_recusada_para_tudo_e_nao_tenta_de_novo(cenario, unifi, partes):
    seguintes = []

    def recusada(ctx):
        raise ErroApi("chave_recusada", "A UniFi recusou a chave (401).")

    partes(("Consoles", recusada), ("WAN", lambda ctx: seguintes.append(1)))
    t = rodar(cenario.org_a, cenario.cliente_a)
    assert t.situacao == Situacao.FALHOU and "401" in t.erro
    assert seguintes == []


def test_parte_grava_so_na_propria_organizacao(cenario, unifi, partes):
    vistos = []

    def olha(ctx):
        with ctx.banco():
            vistos.append(sorted(Cliente.objects.values_list("nome", flat=True)))
        return "ok"

    partes(("Olhar", olha))
    rodar(cenario.org_b, cenario.cliente_b)
    assert vistos == [["Escola do B"]]


@pytest.mark.parametrize("caso,mensagem", [
    ("apagado", "O cliente não existe mais."),
    ("sem_chave", "Cliente sem chave da UniFi."),
    ("sem_console", "Nenhum console acompanhado."),
])
def test_casos_que_nao_adianta_repetir(cenario, unifi, partes, caso, mensagem):
    if caso == "apagado":
        t = coleta.enfileirar_coleta(cenario.org_a.pk, cenario.cliente_a.pk)
        with contexto(organizacao_id=cenario.org_a.pk):
            Cliente.objects.get(pk=cenario.cliente_a.pk).delete()
        executar(pegar_proxima())
        t = Tarefa.objects.get(pk=t.pk)
    else:
        t = rodar(cenario.org_a, getattr(cenario, caso))
    assert t.situacao == Situacao.FALHOU and t.erro == mensagem
    assert unifi == []


def test_pedida_por_usuario_nao_e_automatica_e_passa_o_forcar(cenario, unifi, partes):
    forcados = []
    partes(("Consumo", lambda ctx: forcados.append(ctx.forcar) or "ok"))
    rodar(cenario.org_a, cenario.cliente_a, pedida_por_id=cenario.admin_a.pk, forcar=True)
    assert forcados == [True]
    assert execucoes(cenario.org_a)[0].automatica is False


# Isolamento do registro de execução ----------------------------------------------------

def test_execucao_isolada_por_organizacao(cenario, unifi, partes):
    partes(("Consoles", lambda ctx: "ok"))
    rodar(cenario.org_a, cenario.cliente_a)
    rodar(cenario.org_b, cenario.cliente_b)
    assert [e.cliente_id for e in execucoes(cenario.org_a)] == [cenario.cliente_a.pk]
    with contexto(organizacao_id=cenario.org_a.pk):
        assert sql("select count(*) from coletas_execucaocoleta") == [(1,)]
    assert sql("select count(*) from coletas_execucaocoleta") == [(0,)]
    assert sql(
        "select relrowsecurity, relforcerowsecurity from pg_class where relname = 'coletas_execucaocoleta'"
    ) == [(True, True)]


def test_banco_recusa_execucao_com_cliente_de_outra_organizacao(cenario):
    with contexto(organizacao_id=cenario.org_a.pk):
        with pytest.raises(DatabaseError) as erro, transaction.atomic():
            sql(
                "insert into coletas_execucaocoleta (organizacao_id, cliente_id, automatica, iniciada_em, "
                "resultado, partes) values (%s, %s, true, now(), 'ok', '[]')",
                [cenario.org_a.pk, cenario.cliente_b.pk],
            )
            sql("set constraints all immediate")
        assert "cliente_mesma_org" in str(erro.value)
