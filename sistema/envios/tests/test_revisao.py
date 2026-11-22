"""Revisão de segurança da etapa 5: travas contra envio preso, tela esperando sem fim e reenvio em excesso."""
from datetime import timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from conexoes.models import ChaveUniFi
from envios import rede
from envios.models import ConfigSmtp, Envio, SituacaoEnvio
from envios.views_cliente import MAX_ENVIOS_POR_DIA
from organizacoes.isolamento import contexto

# A fixture automática (e-mail em memória, sem Chromium) vem junto do import.
from .test_envio import (agendar, disparar_e_rodar, envios_de, relatorio_de, rodar_fila,  # noqa: F401
                         sem_chromium_e_email_em_memoria, smtp)

pytestmark = pytest.mark.django_db


def test_erro_inesperado_no_envio_vira_falha_e_nao_fica_enviando(msps, monkeypatch):
    def quebra(*args, **kwargs):
        raise ValueError("algo inesperado")

    monkeypatch.setattr("envios.tarefas.mensagem_do_relatorio", quebra)
    smtp(msps.org_a)
    agendar(msps.org_a, msps.cliente_a)
    disparar_e_rodar()
    [e] = envios_de(msps.org_a)
    assert e.situacao == SituacaoEnvio.FALHOU and e.motivo.endswith("(ValueError).")
    assert "algo inesperado" not in e.motivo


def test_nome_do_cliente_com_quebra_de_linha_nao_quebra_o_assunto(msps):
    with contexto(organizacao_id=msps.org_a.pk):
        msps.cliente_a.nome = "Padaria\ndo A"
        msps.cliente_a.save()
    smtp(msps.org_a)
    agendar(msps.org_a, msps.cliente_a)
    disparar_e_rodar()
    [m] = mail.outbox
    assert "\n" not in m.subject and "Padaria do A" in m.subject


def test_envio_preso_vira_falha_no_historico(msps, entrar_como):
    smtp(msps.org_a)
    agendar(msps.org_a, msps.cliente_a)
    disparar_e_rodar()
    with contexto(organizacao_id=msps.org_a.pk):
        Envio.objects.update(situacao=SituacaoEnvio.PENDENTE, tentativas=0,
                             criado_em=timezone.now() - timedelta(hours=4))
    html = entrar_como(msps.leitor_a).get(reverse("clientes:detalhe", args=[msps.cliente_a.pk])).content.decode()
    assert "O envio não terminou" in html and 'hx-trigger="every 3s"' not in html
    assert envios_de(msps.org_a)[0].situacao == SituacaoEnvio.FALHOU


def test_reenviar_tem_limite_por_dia(msps, entrar_como):
    smtp(msps.org_a)
    agendar(msps.org_a, msps.cliente_a)
    disparar_e_rodar()                      # 1º envio
    r = relatorio_de(msps.org_a)
    client = entrar_como(msps.admin_a)
    url = reverse("envios_cliente:reenviar", args=[msps.cliente_a.pk, r.pk])
    for _ in range(MAX_ENVIOS_POR_DIA - 1):
        client.post(url)
        rodar_fila()
    html = client.post(url, follow=True).content.decode()
    assert "nas últimas 24 horas" in html
    assert len(envios_de(msps.org_a)) == MAX_ENVIOS_POR_DIA


def test_teste_esquecido_para_de_ser_pendente():
    agora = timezone.now()
    config = ConfigSmtp(teste_pedido_em=agora - timedelta(minutes=11))
    chave = ChaveUniFi(teste_pedido_em=agora - timedelta(minutes=11))
    assert not config.teste_pendente and not chave.teste_pendente
    config.teste_pedido_em = chave.teste_pedido_em = agora - timedelta(minutes=1)
    assert config.teste_pendente and chave.teste_pendente


@pytest.mark.parametrize("texto, interno", [("smtp.gmail.com", False), ("8.8.8.8", False), ("localhost", True),
                                            ("mail.localhost", True), ("10.0.0.1", True), ("[::1]", True)])
def test_validacao_do_formulario_distingue_nome_e_ip(texto, interno):
    assert rede.eh_ip_literal_interno(texto) is interno


def test_ip_que_nao_da_para_ler_nao_e_publico():
    assert rede.ip_publico("fe80::1%eth0") is False and rede.ip_publico("lixo") is False


def test_auditoria_registra_troca_de_credencial(msps, entrar_como):
    from auditoria.models import Acao, EventoOrganizacao

    from .test_smtp import salvar
    salvar(entrar_como(msps.admin_a))
    with contexto(organizacao_id=msps.org_a.pk):
        evento = EventoOrganizacao.objects.get(acao=Acao.SMTP_ALTERADO)
    assert evento.detalhes["credencial_trocada"] is True
