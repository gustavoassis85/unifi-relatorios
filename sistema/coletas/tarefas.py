"""Tarefa de coleta de um cliente e a periódica que agenda as coletas de hora em hora."""
import logging
from dataclasses import dataclass, field
from datetime import datetime

from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from clientes.models import Cliente
from cofre.cifra import ErroCofre
from conexoes.models import ChaveUniFi, Console
from organizacoes.isolamento import contexto
from organizacoes.models import Organizacao
from tarefas.fila import ErroDefinitivo, ErroTemporario, enfileirar, tarefa
from tarefas.periodicas import periodica
from unifi.api import ClienteUniFi, ErroApi

from .models import ExecucaoColeta, ResultadoExecucao

log = logging.getLogger("coletas")

TIPO = "coletar_cliente"
PRAZO_CHAMADA = 120                    # segundos por chamada à UniFi (com novas tentativas)
ERROS_TEMPORARIOS = {"rede", "tempo", "limite", "servidor"}

# Partes da coleta, na ordem: (nome, função). Cada parte recebe o Contexto e devolve um
# resumo em texto. As partes são registradas com @parte nas partes seguintes da etapa.
_partes = []


def parte(nome, ordem):
    def registrar(funcao):
        _partes.append((ordem, nome, funcao))
        _partes.sort(key=lambda p: p[0])
        return funcao

    return registrar


@dataclass
class Contexto:
    """O que cada parte da coleta recebe."""

    organizacao_id: int
    cliente: Cliente
    api: ClienteUniFi
    consoles: list            # consoles com "acompanhar" ligado
    agora: datetime
    forcar: bool = False      # refaz consumo e catálogos agora (como o --forcar do MVP)
    extras: dict = field(default_factory=dict)  # uma parte pode deixar dados para as seguintes

    def banco(self):
        """Abre o contexto da organização para ler ou gravar (a RLS só deixa passar a dela)."""
        return contexto(organizacao_id=self.organizacao_id)


def criar_cliente_api(chave_texto):
    """Ponto único de criação do cliente da api.ui.com (os testes trocam esta função)."""
    return ClienteUniFi(chave_texto, prazo=PRAZO_CHAMADA)


def nome_exclusivo(cliente_id):
    return f"{TIPO}:{cliente_id}"


def enfileirar_coleta(organizacao_id, cliente_id, *, pedida_por_id=None, forcar=False):
    return enfileirar(
        TIPO, organizacao_id=organizacao_id, cliente_id=cliente_id,
        exclusiva=nome_exclusivo(cliente_id), pedida_por_id=pedida_por_id, forcar=forcar,
    )


def clientes_para_coletar(organizacao_id):
    """Clientes com chave e pelo menos um console acompanhado."""
    with contexto(organizacao_id=organizacao_id):
        com_chave = ChaveUniFi.objects.values_list("cliente_id", flat=True)
        com_console = Console.objects.filter(acompanhar=True).values_list("cliente_id", flat=True)
        return sorted(set(com_chave) & set(com_console))


@periodica("coletar_clientes", minuto=30)
def agendar_coletas(agora):
    total = 0
    for org_id in Organizacao.objects.filter(ativa=True).values_list("pk", flat=True):
        for cliente_id in clientes_para_coletar(org_id):
            if enfileirar_coleta(org_id, cliente_id):
                total += 1
    log.info("%s coleta(s) agendada(s)", total)
    return total


@tarefa(TIPO)
@sensitive_variables()
def coletar_cliente(tarefa_):
    org_id = tarefa_.organizacao_id
    agora = timezone.now()
    with contexto(organizacao_id=org_id):
        cliente = Cliente.objects.filter(pk=tarefa_.cliente_id).first()
        if cliente is None:
            raise ErroDefinitivo("O cliente não existe mais.")
        chave = ChaveUniFi.objects.filter(cliente=cliente).first()
        consoles = list(Console.objects.filter(cliente=cliente, acompanhar=True))
        execucao = ExecucaoColeta.objects.create(
            cliente=cliente, tarefa_id=tarefa_.pk, automatica=tarefa_.pedida_por_id is None, iniciada_em=agora
        )

    def terminar(resultado, partes):
        with contexto(organizacao_id=org_id):
            execucao.resultado = resultado
            execucao.partes = partes
            execucao.terminada_em = timezone.now()
            execucao.save(update_fields=["resultado", "partes", "terminada_em"])

    if chave is None:
        terminar(ResultadoExecucao.FALHOU, [{"nome": "Chave", "ok": False, "mensagem": "Cliente sem chave da UniFi."}])
        raise ErroDefinitivo("Cliente sem chave da UniFi.")
    if not consoles:
        terminar(ResultadoExecucao.FALHOU, [{"nome": "Consoles", "ok": False, "mensagem": "Nenhum console acompanhado."}])
        raise ErroDefinitivo("Nenhum console acompanhado.")
    try:
        api = criar_cliente_api(chave.abrir())
    except ErroCofre as erro:
        terminar(ResultadoExecucao.FALHOU, [{"nome": "Chave", "ok": False, "mensagem": str(erro)}])
        raise ErroDefinitivo(str(erro)) from None

    ctx = Contexto(org_id, cliente, api, consoles, agora, forcar=bool(tarefa_.parametros.get("forcar")))
    partes, codigos = [], []
    for _, nome, funcao in _partes:
        try:
            mensagem = funcao(ctx)
        except ErroApi as erro:
            partes.append({"nome": nome, "ok": False, "mensagem": erro.mensagem})
            codigos.append(erro.codigo)
            if erro.codigo == "chave_recusada":
                break  # as outras partes falhariam do mesmo jeito
        except Exception as erro:  # noqa: BLE001 - uma parte com erro não derruba as outras
            log.exception("Erro inesperado na coleta %s do cliente %s", nome, cliente.pk)
            partes.append({"nome": nome, "ok": False, "mensagem": f"Erro inesperado ({erro.__class__.__name__})."})
            codigos.append("inesperado")
        else:
            partes.append({"nome": nome, "ok": True, "mensagem": str(mensagem or "")[:300]})

    falhas = [p for p in partes if not p["ok"]]
    if not falhas:
        terminar(ResultadoExecucao.OK, partes)
        return
    if len(falhas) < len(partes):
        terminar(ResultadoExecucao.PARCIAL, partes)
        return
    terminar(ResultadoExecucao.FALHOU, partes)
    if "chave_recusada" in codigos:
        raise ErroDefinitivo(falhas[0]["mensagem"])
    if set(codigos) <= ERROS_TEMPORARIOS:
        raise ErroTemporario(falhas[0]["mensagem"])
    raise ErroDefinitivo(falhas[0]["mensagem"])
