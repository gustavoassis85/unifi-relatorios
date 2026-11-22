"""Testar a conexão de um cliente com a UniFi e atualizar a lista de consoles.

O clique em "Testar conexão" só enfileira (pedir_teste). O trabalhador roda executar_teste:
lê a chave numa transação curta, consulta a UniFi FORA de transação (até 30 s, sem segurar
o banco) e grava o resultado e os consoles noutra transação curta.
"""
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from auditoria.models import Acao
from auditoria.registro import registrar
from cofre.cifra import ErroCofre
from organizacoes.isolamento import contexto, exigir_organizacao
from tarefas.fila import enfileirar, tarefa
from unifi.api import ClienteUniFi, ErroApi, resumir_hosts

from .models import ChaveUniFi, Console

PRAZO_TESTE = 30           # segundos
LIMITE_POR_MINUTO = 5      # testes por organização


@dataclass
class Resultado:
    ok: bool
    codigo: str            # "ok" ou o código do ErroApi / "limite_sistema" / "cofre"
    mensagem: str
    consoles: int = 0
    conectados: int = 0


def criar_cliente_api(chave_texto):
    """Ponto único de criação do cliente da api.ui.com (os testes trocam esta função)."""
    return ClienteUniFi(chave_texto, prazo=PRAZO_TESTE)


def reservar_teste(organizacao_id):
    """Conta os testes da organização no último minuto. False se passou do limite."""
    nome = f"teste-conexao:{organizacao_id}"
    cache.add(nome, 0, timeout=60)
    try:
        return cache.incr(nome) <= LIMITE_POR_MINUTO
    except ValueError:  # expirou entre o add e o incr
        cache.add(nome, 1, timeout=60)
        return True


def sincronizar_consoles(cliente, resumos, agora=None):
    """Grava os consoles que a chave enxergou. Devolve (total, conectados).

    - Console novo: acompanhado se está conectado e não é acompanhado por outro cliente
      da organização. Desconectado ou antigo entra sem acompanhar.
    - Console que já existia: atualiza nome, modelo, situação e versões; "acompanhar" não muda.
    - Console que sumiu da conta: fica marcado como "não aparece mais na conta".
    """
    agora = agora or timezone.now()
    existentes = {c.host_id: c for c in Console.objects.filter(cliente=cliente)}
    acompanhados_em_outros = set(
        Console.objects.filter(acompanhar=True).exclude(cliente=cliente).values_list("host_id", flat=True)
    )
    vistos = set()
    for dados in resumos:
        host_id = dados["host_id"]
        if host_id in vistos:
            continue
        vistos.add(host_id)
        campos = {k: dados[k] for k in ("nome", "modelo", "tipo", "conectado", "firmware", "versao_network")}
        console = existentes.get(host_id)
        if console is None:
            console = Console(
                cliente=cliente,
                host_id=host_id,
                acompanhar=dados["conectado"] and host_id not in acompanhados_em_outros,
                primeiro_visto_em=agora,
            )
        for nome, valor in campos.items():
            setattr(console, nome, valor)
        console.na_conta = True
        console.visto_em = agora
        console.save()

    for host_id, console in existentes.items():
        if host_id not in vistos and console.na_conta:
            console.na_conta = False
            console.conectado = False
            console.save(update_fields=["na_conta", "conectado"])

    conectados = sum(1 for d in resumos if d["conectado"])
    return len(vistos), conectados


TIPO_TESTE = "testar_conexao"


def pedir_teste(chave, usuario):
    """Na requisição: confere o limite e enfileira. Devolve uma mensagem de erro ou ""."""
    if not reservar_teste(exigir_organizacao()):
        # Não conta como teste: nada é gravado na chave.
        return "Muitos testes seguidos. Espere um minuto e tente de novo."
    enfileirar(TIPO_TESTE, organizacao_id=chave.organizacao_id, cliente_id=chave.cliente_id,
               exclusiva=f"{TIPO_TESTE}:{chave.cliente_id}", pedida_por_id=usuario.pk, max_tentativas=1)
    chave.teste_pedido_em = timezone.now()
    chave.save(update_fields=["teste_pedido_em"])
    return ""


@sensitive_variables()
def executar_teste(organizacao_id, cliente_id, usuario_id=None):
    """No trabalhador, fora de transação. Devolve o Resultado (ou None se a chave sumiu)."""
    with contexto(organizacao_id=organizacao_id):
        chave = ChaveUniFi.objects.filter(cliente_id=cliente_id).first()
        if chave is None:
            return None
        try:
            texto, erro_cofre = chave.abrir(), None
        except ErroCofre as erro:
            texto, erro_cofre = None, erro

    hosts, resultado = None, None
    if erro_cofre is not None:
        resultado = Resultado(False, "cofre", str(erro_cofre))
    else:
        try:
            hosts = criar_cliente_api(texto).listar_hosts()     # sem transação aberta
        except ErroApi as erro:
            resultado = Resultado(False, erro.codigo, erro.mensagem)
    texto = None

    with contexto(organizacao_id=organizacao_id):
        chave = ChaveUniFi.objects.select_related("cliente").filter(cliente_id=cliente_id).first()
        if chave is None:   # apagada enquanto a UniFi respondia
            return None
        if resultado is None:
            total, conectados = sincronizar_consoles(chave.cliente, resumir_hosts(hosts))
            if total == 0:
                mensagem = "A chave funciona, mas a conta não tem nenhum console."
            else:
                mensagem = f"Conexão funcionou: {total} console(s), {conectados} conectado(s)."
            resultado = Resultado(True, "ok", mensagem, total, conectados)
        chave.testada_em = timezone.now()
        chave.teste_ok = resultado.ok
        chave.teste_resultado = resultado.mensagem[:300]
        chave.save(update_fields=["testada_em", "teste_ok", "teste_resultado"])
        usuario = get_user_model().objects.filter(pk=usuario_id).first() if usuario_id else None
        registrar(None, Acao.CONEXAO_TESTADA, usuario=usuario, cliente_id=chave.cliente_id,
                  cliente=chave.cliente.nome, resultado=resultado.codigo, consoles=resultado.consoles,
                  conectados=resultado.conectados)
    return resultado


@tarefa(TIPO_TESTE)
def testar_conexao(tarefa_):
    executar_teste(tarefa_.organizacao_id, tarefa_.cliente_id, tarefa_.pedida_por_id)
