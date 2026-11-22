"""Tarefas do trabalhador para e-mail: o teste do SMTP e o envio dos relatórios.

Envio: quando um relatório agendado fica pronto (sinal relatorio_pronto), nasce um Envio.
Sem SMTP ativo, o Envio já nasce "não enviado" (o relatório continua no histórico: plano B).
Com SMTP, a tarefa enviar_relatorio tenta até 3 vezes: na hora, depois de 10 min e de 1 h.
Os e-mails dos destinatários nunca vão para o log.
"""
import logging
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.dispatch import receiver
from django.utils import timezone

from organizacoes.isolamento import contexto
from relatorios.models import Origem, Relatorio, SituacaoRelatorio
from relatorios.servicos import marca_da_organizacao, nome_do_pdf
from relatorios.sinais import relatorio_pronto
from tarefas.fila import ErroDefinitivo, enfileirar, tarefa

from .correio import ErroEnvio, mandar, mensagem_de_teste
from .models import ConfigSmtp, Envio, SituacaoEnvio

log = logging.getLogger("envios")

TESTE = "testar_smtp"
ENVIO = "enviar_relatorio"
ESPERAS = [timedelta(minutes=10), timedelta(hours=1)]   # antes da 2ª e da 3ª tentativa
MAX_TENTATIVAS = len(ESPERAS) + 1
SEM_SMTP = "SMTP não configurado: o relatório ficou só no histórico."
SMTP_DESLIGADO = "O servidor de e-mail está desligado: o relatório ficou só no histórico."


# --- teste do SMTP -----------------------------------------------------------

def enfileirar_teste(config, usuario):
    return enfileirar(TESTE, organizacao_id=config.organizacao_id, exclusiva=f"{TESTE}:{config.organizacao_id}",
                      pedida_por_id=usuario.pk, max_tentativas=1, usuario_id=usuario.pk)


@tarefa(TESTE)
def testar_smtp(tarefa_):
    org_id = tarefa_.organizacao_id
    usuario = get_user_model().objects.filter(pk=tarefa_.parametros.get("usuario_id")).first()
    with contexto(organizacao_id=org_id):
        config = ConfigSmtp.objects.first()
        if config is None:
            raise ErroDefinitivo("O servidor de e-mail não está mais configurado.")
        if usuario is None:
            resultado, ok = "O usuário que pediu o teste não existe mais.", False
        else:
            try:
                mandar(config, mensagem_de_teste(usuario.email))
                resultado, ok = f"E-mail de teste enviado para {usuario.email}.", True
            except ErroEnvio as erro:
                resultado, ok = str(erro), False
        config.testado_em = timezone.now()
        config.teste_ok = ok
        config.teste_resultado = resultado[:300]
        config.save(update_fields=["testado_em", "teste_ok", "teste_resultado"])
    log.info("Teste de SMTP da organização %s: %s", org_id, "ok" if ok else "falhou")


# --- envio dos relatórios ----------------------------------------------------

def _smtp_impede():
    """Motivo para não enviar (sem SMTP ou desligado), ou vazio se dá para enviar."""
    config = ConfigSmtp.objects.only("ativo").first()
    if config is None:
        return SEM_SMTP
    return "" if config.ativo else SMTP_DESLIGADO


def _enfileirar_envio(envio, executar_em=None):
    return enfileirar(ENVIO, organizacao_id=envio.organizacao_id, cliente_id=envio.cliente_id,
                      exclusiva=f"{ENVIO}:{envio.pk}:{envio.tentativas + 1}", pedida_por_id=envio.pedido_por_id,
                      executar_em=executar_em, max_tentativas=1, envio_id=envio.pk)


def criar_envio(relatorio, destinatarios, pedido_por=None):
    """Cria o Envio e, se houver SMTP ativo, enfileira. Chamar dentro do contexto da organização."""
    motivo = _smtp_impede()
    envio = Envio.objects.create(
        cliente_id=relatorio.cliente_id, relatorio=relatorio, destinatarios=list(destinatarios),
        pedido_por=pedido_por, situacao=SituacaoEnvio.NAO_ENVIADO if motivo else SituacaoEnvio.PENDENTE,
        motivo=motivo,
    )
    if not motivo:
        _enfileirar_envio(envio)
    return envio


@receiver(relatorio_pronto, dispatch_uid="envios_ao_ficar_pronto")
def ao_ficar_pronto(sender, relatorio, **kwargs):
    if relatorio.origem != Origem.AGENDADO or relatorio.agendamento_id is None:
        return
    with contexto(organizacao_id=relatorio.organizacao_id):
        agendamento = relatorio.agendamento
        if agendamento is None or not agendamento.destinatarios:
            return   # sem destinatários: o agendamento só gera
        criar_envio(relatorio, agendamento.destinatarios)


def mensagem_do_relatorio(relatorio, destinatarios):
    marca = marca_da_organizacao()
    cliente = relatorio.cliente
    linhas = [
        "Olá,",
        "",
        f"Segue em anexo o relatório de saúde da rede de {cliente.nome}, referente a: {relatorio.rotulo.lower()}.",
        "",
        "Qualquer dúvida, fale com a gente.",
        "",
        marca.empresa,
    ]
    if marca.contato:
        linhas.append(marca.contato)
    mensagem = EmailMessage(
        subject=f"Relatório de saúde da rede — {cliente.nome} — {relatorio.rotulo}",
        body="\n".join(linhas) + "\n",
        to=list(destinatarios),
    )
    mensagem.attach(nome_do_pdf(cliente, relatorio), bytes(relatorio.pdf), "application/pdf")
    return mensagem


@tarefa(ENVIO)
def enviar_relatorio(tarefa_):
    org_id = tarefa_.organizacao_id
    with contexto(organizacao_id=org_id):
        envio = Envio.objects.filter(pk=tarefa_.parametros.get("envio_id")).first()
        if envio is None:
            raise ErroDefinitivo("O envio não existe mais (o relatório foi apagado).")
        if envio.situacao != SituacaoEnvio.PENDENTE:
            return
        envio.tentativas += 1
        relatorio = Relatorio.objects.select_related("cliente").filter(pk=envio.relatorio_id).first()
        motivo = _smtp_impede()
        if motivo:
            envio.situacao, envio.motivo = SituacaoEnvio.NAO_ENVIADO, motivo
        elif relatorio is None or relatorio.situacao != SituacaoRelatorio.PRONTO or not relatorio.pdf:
            envio.situacao, envio.motivo = SituacaoEnvio.FALHOU, "O relatório não está pronto para envio."
        else:
            try:
                mandar(ConfigSmtp.objects.first(), mensagem_do_relatorio(relatorio, envio.destinatarios))
                envio.situacao, envio.motivo, envio.enviado_em = SituacaoEnvio.ENVIADO, "", timezone.now()
            except ErroEnvio as erro:
                envio.motivo = str(erro)[:300]
                if erro.temporario and envio.tentativas < MAX_TENTATIVAS:
                    _enfileirar_envio(envio, executar_em=timezone.now() + ESPERAS[envio.tentativas - 1])
                else:
                    envio.situacao = SituacaoEnvio.FALHOU
        envio.save(update_fields=["tentativas", "situacao", "motivo", "enviado_em"])
    log.info("Envio %s do relatório %s: %s (tentativa %s, %s destinatário(s))", envio.pk, envio.relatorio_id,
             envio.situacao, envio.tentativas, len(envio.destinatarios))
