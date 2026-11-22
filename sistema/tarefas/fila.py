"""Enfileirar, pegar e executar tarefas.

Cada tipo de tarefa é uma função registrada com @tarefa("tipo"). A função recebe a
Tarefa e roda FORA de transação: para ler ou gravar dado de MSP, ela abre
contexto(organizacao_id=tarefa.organizacao_id). Sem isso, a RLS não entrega nem aceita nada.
"""
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Situacao, Tarefa

log = logging.getLogger("tarefas")

TRAVADA_APOS = timedelta(minutes=30)
ESPERAS = [timedelta(minutes=2), timedelta(minutes=8), timedelta(minutes=30)]
GUARDAR_FEITAS_POR = timedelta(days=30)

_tipos = {}


class ErroTemporario(Exception):
    """Vale tentar de novo mais tarde (rede, limite da UniFi). A mensagem vai para a tela."""


class ErroDefinitivo(Exception):
    """Não adianta tentar de novo (chave recusada, cliente apagado). A mensagem vai para a tela."""


def tarefa(tipo):
    def registrar(funcao):
        _tipos[tipo] = funcao
        return funcao

    return registrar


def enfileirar(tipo, *, organizacao_id=None, cliente_id=None, exclusiva=None, pedida_por_id=None,
               executar_em=None, max_tentativas=3, **parametros):
    """Cria a tarefa. Devolve None se já há uma igual (mesmo "exclusiva") na fila ou rodando."""
    if tipo not in _tipos:
        raise ValueError(f"Tipo de tarefa desconhecido: {tipo}")
    try:
        with transaction.atomic():
            return Tarefa.objects.create(
                tipo=tipo, organizacao_id=organizacao_id, cliente_id=cliente_id, exclusiva=exclusiva,
                pedida_por_id=pedida_por_id, executar_em=executar_em or timezone.now(),
                max_tentativas=max_tentativas, parametros=parametros,
            )
    except IntegrityError:
        return None


def pegar_proxima(agora=None):
    """Reserva a próxima tarefa vencida. Dois trabalhadores nunca pegam a mesma (skip locked)."""
    agora = agora or timezone.now()
    with transaction.atomic():
        tarefa_ = (
            Tarefa.objects.select_for_update(skip_locked=True)
            .filter(situacao=Situacao.FILA, executar_em__lte=agora)
            .order_by("executar_em", "pk")
            .first()
        )
        if tarefa_ is None:
            return None
        tarefa_.situacao = Situacao.RODANDO
        tarefa_.iniciada_em = agora
        tarefa_.tentativas += 1
        tarefa_.save(update_fields=["situacao", "iniciada_em", "tentativas"])
        return tarefa_


def _terminar(tarefa_, situacao, erro=""):
    tarefa_.situacao = situacao
    tarefa_.erro = erro[:500]
    tarefa_.terminada_em = timezone.now()
    tarefa_.save(update_fields=["situacao", "erro", "terminada_em"])


def _de_novo_mais_tarde(tarefa_, erro):
    if tarefa_.tentativas >= tarefa_.max_tentativas:
        _terminar(tarefa_, Situacao.FALHOU, erro)
        return
    espera = ESPERAS[min(tarefa_.tentativas - 1, len(ESPERAS) - 1)]
    tarefa_.situacao = Situacao.FILA
    tarefa_.erro = erro[:500]
    tarefa_.executar_em = timezone.now() + espera
    tarefa_.save(update_fields=["situacao", "erro", "executar_em"])


def executar(tarefa_):
    """Roda a tarefa reservada e registra o resultado. Nunca deixa a exceção escapar."""
    funcao = _tipos.get(tarefa_.tipo)
    if funcao is None:
        _terminar(tarefa_, Situacao.FALHOU, f"Tipo de tarefa desconhecido: {tarefa_.tipo}")
        return
    try:
        funcao(tarefa_)
    except ErroDefinitivo as erro:
        _terminar(tarefa_, Situacao.FALHOU, str(erro))
    except ErroTemporario as erro:
        _de_novo_mais_tarde(tarefa_, str(erro))
    except Exception as erro:  # noqa: BLE001 - erro inesperado não derruba o trabalhador
        # Na tela e no banco só o tipo do erro (a mensagem pode ter dado que não deve sair daqui);
        # o detalhe completo vai para o log do servidor.
        log.exception("Erro inesperado na tarefa %s #%s", tarefa_.tipo, tarefa_.pk)
        _de_novo_mais_tarde(tarefa_, f"Erro inesperado ({erro.__class__.__name__}).")
    else:
        _terminar(tarefa_, Situacao.FEITA)


def recuperar_travadas(agora=None):
    """Tarefa "rodando" há mais de 30 min (trabalhador caiu): volta para a fila ou falha."""
    agora = agora or timezone.now()
    total = 0
    with transaction.atomic():
        travadas = Tarefa.objects.select_for_update(skip_locked=True).filter(
            situacao=Situacao.RODANDO, iniciada_em__lt=agora - TRAVADA_APOS
        )
        for tarefa_ in travadas:
            _de_novo_mais_tarde(tarefa_, "O trabalhador parou no meio desta tarefa.")
            total += 1
    return total


def apagar_antigas(agora=None):
    agora = agora or timezone.now()
    apagadas, _ = Tarefa.objects.filter(
        situacao__in=[Situacao.FEITA, Situacao.FALHOU], terminada_em__lt=agora - GUARDAR_FEITAS_POR
    ).delete()
    return apagadas
