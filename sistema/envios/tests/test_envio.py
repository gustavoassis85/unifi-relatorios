"""Envio dos relatórios agendados: anexo, plano B sem SMTP, tentativas, reenvio, papéis e isolamento."""
import smtplib
import socket
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from django.core import mail
from django.db import connection
from django.urls import reverse
from django.utils import timezone

import relatorios.tarefas as tarefa_relatorio
from auditoria.models import Acao, EventoOrganizacao
from envios.disparo import disparar_agendamentos
from envios.models import Agendamento, ConfigSmtp, Envio, Frequencia, SituacaoEnvio
from envios.tarefas import ESPERAS
from organizacoes.isolamento import contexto
from relatorios.models import Origem, Relatorio, SituacaoRelatorio
from relatorios.periodos import FUSO
from tarefas.fila import executar, pegar_proxima
from tarefas.models import Tarefa

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.7 relatorio de teste"
MARCADO = datetime(2026, 12, 1, 8, tzinfo=FUSO)
DESTINOS = ["dono@padaria.com.br", "financeiro@padaria.com.br"]


@pytest.fixture(autouse=True)
def sem_chromium_e_email_em_memoria(settings, monkeypatch):
    settings.ENVIOS_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    monkeypatch.setattr(tarefa_relatorio, "montar",
                        lambda *a: SimpleNamespace(html="<html></html>", higiene=[], erros=[]))
    monkeypatch.setattr(tarefa_relatorio, "gerar_pdf", lambda html: PDF)


def smtp(org, ativo=True):
    with contexto(organizacao_id=org.pk):
        config = ConfigSmtp(servidor="smtp.exemplo.com", porta=587, usuario="u", remetente="rel@msp.com",
                            ativo=ativo)
        config.definir_senha("senha-forte-123")
        config.save()


def agendar(org, cliente, destinatarios=DESTINOS):
    with contexto(organizacao_id=org.pk):
        return Agendamento.objects.create(cliente=cliente, frequencia=Frequencia.MENSAL, dia_do_mes=1, hora=8,
                                          proxima_execucao=MARCADO, destinatarios=destinatarios)


def rodar_fila(ate=None):
    while (t := pegar_proxima(ate)) is not None:
        executar(t)


def disparar_e_rodar(ate=None):
    disparar_agendamentos(MARCADO + timedelta(minutes=1))
    rodar_fila(ate)


def envios_de(org):
    with contexto(organizacao_id=org.pk):
        return list(Envio.objects.order_by("pk"))


def relatorio_de(org):
    with contexto(organizacao_id=org.pk):
        return Relatorio.objects.get()


def test_agendado_sai_por_email_com_o_pdf(msps):
    smtp(msps.org_a)
    agendar(msps.org_a, msps.cliente_a)
    disparar_e_rodar()
    assert relatorio_de(msps.org_a).situacao == SituacaoRelatorio.PRONTO
    [e] = envios_de(msps.org_a)
    assert (e.situacao, e.tentativas, e.destinatarios) == (SituacaoEnvio.ENVIADO, 1, DESTINOS)
    assert e.enviado_em is not None
    [m] = mail.outbox
    assert m.to == DESTINOS and m.from_email == "MSP A <rel@msp.com>"
    assert m.subject == "Relatório de saúde da rede — Padaria do A — Novembro de 2026"
    assert "Padaria do A" in m.body and "novembro de 2026" in m.body
    [(nome, conteudo, tipo)] = m.attachments
    assert (nome, conteudo, tipo) == ("saude-da-rede-padaria-do-a-novembro-de-2026.pdf", PDF, "application/pdf")


def test_sem_smtp_o_relatorio_fica_no_historico(msps, entrar_como):
    agendar(msps.org_a, msps.cliente_a)
    disparar_e_rodar()
    assert relatorio_de(msps.org_a).situacao == SituacaoRelatorio.PRONTO
    [e] = envios_de(msps.org_a)
    assert e.situacao == SituacaoEnvio.NAO_ENVIADO and "SMTP não configurado" in e.motivo
    assert mail.outbox == [] and not Tarefa.objects.filter(tipo="enviar_relatorio").exists()
    html = entrar_como(msps.leitor_a).get(reverse("clientes:detalhe", args=[msps.cliente_a.pk])).content.decode()
    assert "Não enviado: SMTP não configurado" in html


def test_smtp_desligado_tambem_nao_envia(msps):
    smtp(msps.org_a, ativo=False)
    agendar(msps.org_a, msps.cliente_a)
    disparar_e_rodar()
    [e] = envios_de(msps.org_a)
    assert e.situacao == SituacaoEnvio.NAO_ENVIADO and "desligado" in e.motivo
    assert mail.outbox == []


def test_sem_destinatarios_so_gera(msps):
    smtp(msps.org_a)
    agendar(msps.org_a, msps.cliente_a, destinatarios=[])
    disparar_e_rodar()
    assert relatorio_de(msps.org_a).situacao == SituacaoRelatorio.PRONTO
    assert envios_de(msps.org_a) == [] and mail.outbox == []


def test_relatorio_manual_nao_e_enviado(msps, entrar_como):
    smtp(msps.org_a)
    entrar_como(msps.admin_a).post(reverse("relatorios_cliente:gerar", args=[msps.cliente_a.pk]), {"periodo": "7d"})
    rodar_fila()
    assert relatorio_de(msps.org_a).origem == Origem.MANUAL
    assert envios_de(msps.org_a) == [] and mail.outbox == []


def test_falha_temporaria_tenta_3_vezes_e_desiste(msps, monkeypatch):
    def fora_do_ar(*args, **kwargs):
        raise socket.timeout

    monkeypatch.setattr(mail.backends.locmem.EmailBackend, "send_messages", fora_do_ar)
    smtp(msps.org_a)
    agendar(msps.org_a, msps.cliente_a)
    disparar_e_rodar()
    [e] = envios_de(msps.org_a)
    assert (e.situacao, e.tentativas) == (SituacaoEnvio.PENDENTE, 1) and "não respondeu" in e.motivo
    proxima = Tarefa.objects.filter(tipo="enviar_relatorio", situacao="fila").get()
    assert timedelta(minutes=9) < proxima.executar_em - timezone.now() <= ESPERAS[0]
    rodar_fila(timezone.now() + timedelta(minutes=11))
    [e] = envios_de(msps.org_a)
    assert (e.situacao, e.tentativas) == (SituacaoEnvio.PENDENTE, 2)
    rodar_fila(timezone.now() + timedelta(hours=2))
    [e] = envios_de(msps.org_a)
    assert (e.situacao, e.tentativas) == (SituacaoEnvio.FALHOU, 3)
    assert not Tarefa.objects.filter(tipo="enviar_relatorio", situacao="fila").exists()


def test_senha_recusada_nao_tenta_de_novo(msps, monkeypatch):
    def recusa(*args, **kwargs):
        raise smtplib.SMTPAuthenticationError(535, b"no")

    monkeypatch.setattr(mail.backends.locmem.EmailBackend, "send_messages", recusa)
    smtp(msps.org_a)
    agendar(msps.org_a, msps.cliente_a)
    disparar_e_rodar()
    [e] = envios_de(msps.org_a)
    assert (e.situacao, e.tentativas) == (SituacaoEnvio.FALHOU, 1)
    assert e.motivo == "O servidor de e-mail recusou o usuário ou a senha."


def test_reenviar_depois_de_falhar(msps, entrar_como, monkeypatch):
    agendar(msps.org_a, msps.cliente_a)
    disparar_e_rodar()                                   # sem SMTP: não enviado
    smtp(msps.org_a)
    r = relatorio_de(msps.org_a)
    client = entrar_como(msps.operador_a)
    html = client.get(reverse("clientes:detalhe", args=[msps.cliente_a.pk])).content.decode()
    assert reverse("envios_cliente:reenviar", args=[msps.cliente_a.pk, r.pk]) in html
    html = client.post(reverse("envios_cliente:reenviar", args=[msps.cliente_a.pk, r.pk]), follow=True)
    assert "Reenvio na fila." in html.content.decode()
    rodar_fila()
    envios = envios_de(msps.org_a)
    assert [e.situacao for e in envios] == [SituacaoEnvio.NAO_ENVIADO, SituacaoEnvio.ENVIADO]
    assert envios[1].pedido_por == msps.operador_a and len(mail.outbox) == 1
    with contexto(organizacao_id=msps.org_a.pk):
        evento = EventoOrganizacao.objects.get(acao=Acao.RELATORIO_REENVIADO)
    assert evento.detalhes["destinatarios"] == 2 and "padaria.com.br" not in str(evento.detalhes)


def test_reenviar_sem_smtp_avisa(msps, entrar_como):
    agendar(msps.org_a, msps.cliente_a)
    disparar_e_rodar()
    r = relatorio_de(msps.org_a)
    html = entrar_como(msps.admin_a).post(reverse("envios_cliente:reenviar", args=[msps.cliente_a.pk, r.pk]),
                                          follow=True).content.decode()
    assert "Não enviado: SMTP não configurado" in html


def test_reenviar_relatorio_manual_e_recusado(msps, entrar_como):
    smtp(msps.org_a)
    client = entrar_como(msps.admin_a)
    client.post(reverse("relatorios_cliente:gerar", args=[msps.cliente_a.pk]), {"periodo": "7d"})
    rodar_fila()
    r = relatorio_de(msps.org_a)
    html = client.post(reverse("envios_cliente:reenviar", args=[msps.cliente_a.pk, r.pk]), follow=True)
    assert "não tem agendamento com destinatários" in html.content.decode()
    assert envios_de(msps.org_a) == []


def test_leitura_nao_reenvia(msps, entrar_como):
    smtp(msps.org_a)
    agendar(msps.org_a, msps.cliente_a)
    disparar_e_rodar()
    r = relatorio_de(msps.org_a)
    client = entrar_como(msps.leitor_a)
    assert "Reenviar" not in client.get(reverse("clientes:detalhe", args=[msps.cliente_a.pk])).content.decode()
    assert client.post(reverse("envios_cliente:reenviar", args=[msps.cliente_a.pk, r.pk])).status_code == 403
    assert len(envios_de(msps.org_a)) == 1


def test_msp_a_nao_reenvia_nem_ve_envio_do_b(msps, entrar_como):
    smtp(msps.org_b)
    agendar(msps.org_b, msps.cliente_b, destinatarios=["diretor@escola.com"])
    disparar_e_rodar()
    rb = relatorio_de(msps.org_b)
    client = entrar_como(msps.admin_a)
    for cliente_pk in (msps.cliente_b.pk, msps.cliente_a.pk):
        assert client.post(reverse("envios_cliente:reenviar", args=[cliente_pk, rb.pk])).status_code == 404
    assert len(envios_de(msps.org_b)) == 1 and envios_de(msps.org_a) == []
    with connection.cursor() as cur:
        cur.execute("select relrowsecurity, relforcerowsecurity from pg_class where relname = 'envios_envio'")
        assert cur.fetchone() == (True, True)
        cur.execute("select count(*) from envios_envio")
        assert cur.fetchone() == (0,)


def test_envio_apagado_junto_com_o_relatorio(msps):
    smtp(msps.org_a)
    agendar(msps.org_a, msps.cliente_a)
    disparar_e_rodar()
    from relatorios.tarefas import apagar_relatorios_antigos
    apagar_relatorios_antigos(MARCADO + timedelta(days=400))
    assert envios_de(msps.org_a) == []


def test_log_nao_tem_os_emails(msps, caplog):
    smtp(msps.org_a)
    agendar(msps.org_a, msps.cliente_a)
    with caplog.at_level("INFO"):
        disparar_e_rodar()
    assert "padaria.com.br" not in caplog.text
