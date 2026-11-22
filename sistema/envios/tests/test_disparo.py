"""Disparo dos agendamentos: cria o relatório na hora, não duplica, respeita pausa e isolamento."""
from datetime import datetime, timedelta

import pytest
from django.urls import reverse

from envios.disparo import disparar_agendamentos, disparar_da_organizacao
from envios.models import Agendamento, Frequencia
from organizacoes.isolamento import contexto
from relatorios.models import Origem, Relatorio, SituacaoRelatorio
from relatorios.periodos import FUSO
from tarefas.models import Tarefa

pytestmark = pytest.mark.django_db

MARCADO = datetime(2026, 12, 1, 8, tzinfo=FUSO)


def criar(cliente, org, **campos):
    dados = {"frequencia": Frequencia.MENSAL, "dia_do_mes": 1, "hora": 8, "proxima_execucao": MARCADO,
             "destinatarios": ["dono@padaria.com.br"], **campos}
    with contexto(organizacao_id=org.pk):
        return Agendamento.objects.create(cliente=cliente, **dados)


def relatorios_de(org):
    with contexto(organizacao_id=org.pk):
        return list(Relatorio.objects.order_by("pk"))


def recarregar(agendamento, org):
    with contexto(organizacao_id=org.pk):
        return Agendamento.objects.get(pk=agendamento.pk)


def test_vencido_gera_o_relatorio_do_mes_anterior(msps):
    a = criar(msps.cliente_a, msps.org_a)
    agora = MARCADO + timedelta(minutes=1)
    assert disparar_agendamentos(agora) == 1
    [r] = relatorios_de(msps.org_a)
    assert (r.origem, r.agendamento_id, r.situacao, r.rotulo) == (Origem.AGENDADO, a.pk, SituacaoRelatorio.GERANDO,
                                                                  "Novembro de 2026")
    assert r.inicio == datetime(2026, 11, 1, tzinfo=FUSO) and r.pedido_por is None
    tarefa = Tarefa.objects.get(tipo="gerar_relatorio")
    assert tarefa.parametros["relatorio_id"] == r.pk and tarefa.organizacao_id == msps.org_a.pk
    a = recarregar(a, msps.org_a)
    assert a.ultima_execucao == agora and a.proxima_execucao == datetime(2027, 1, 1, 8, tzinfo=FUSO)


def test_antes_da_hora_nao_gera(msps):
    criar(msps.cliente_a, msps.org_a)
    assert disparar_agendamentos(MARCADO - timedelta(minutes=1)) == 0
    assert relatorios_de(msps.org_a) == []


def test_pausado_nao_gera(msps):
    criar(msps.cliente_a, msps.org_a, ativo=False)
    assert disparar_agendamentos(MARCADO + timedelta(days=3)) == 0


def test_rodar_de_novo_nao_duplica(msps):
    criar(msps.cliente_a, msps.org_a)
    agora = MARCADO + timedelta(minutes=1)
    disparar_agendamentos(agora)
    disparar_agendamentos(agora + timedelta(minutes=5))
    assert len(relatorios_de(msps.org_a)) == 1


def test_trabalhador_parado_semanas_roda_uma_vez(msps):
    a = criar(msps.cliente_a, msps.org_a, frequencia=Frequencia.SEMANAL, dia_do_mes=None, dia_da_semana=0,
              proxima_execucao=datetime(2026, 11, 2, 8, tzinfo=FUSO))
    agora = datetime(2026, 11, 25, 10, tzinfo=FUSO)   # perdeu 4 segundas
    assert disparar_agendamentos(agora) == 1
    [r] = relatorios_de(msps.org_a)
    assert r.fim == datetime(2026, 11, 2, 8, tzinfo=FUSO) and r.rotulo == "Últimos 7 dias"
    assert recarregar(a, msps.org_a).proxima_execucao == datetime(2026, 11, 30, 8, tzinfo=FUSO)


def test_nao_cria_outro_se_o_anterior_ainda_gera(msps):
    a = criar(msps.cliente_a, msps.org_a)
    disparar_agendamentos(MARCADO + timedelta(minutes=1))
    with contexto(organizacao_id=msps.org_a.pk):
        Agendamento.objects.filter(pk=a.pk).update(proxima_execucao=MARCADO + timedelta(hours=1))
    assert disparar_da_organizacao(msps.org_a.pk, MARCADO + timedelta(hours=1, minutes=1)) == 0
    assert len(relatorios_de(msps.org_a)) == 1
    assert recarregar(a, msps.org_a).proxima_execucao > MARCADO + timedelta(hours=1)


def test_cada_organizacao_dispara_os_seus(msps):
    criar(msps.cliente_a, msps.org_a)
    criar(msps.cliente_b, msps.org_b)
    assert disparar_agendamentos(MARCADO + timedelta(minutes=1)) == 2
    [ra], [rb] = relatorios_de(msps.org_a), relatorios_de(msps.org_b)
    assert (ra.cliente_id, ra.organizacao_id) == (msps.cliente_a.pk, msps.org_a.pk)
    assert (rb.cliente_id, rb.organizacao_id) == (msps.cliente_b.pk, msps.org_b.pk)


def test_erro_num_msp_nao_segura_os_outros(msps, monkeypatch):
    import envios.disparo as disparo

    criar(msps.cliente_a, msps.org_a)
    criar(msps.cliente_b, msps.org_b)
    original = disparo.disparar_da_organizacao

    def quebra_no_a(org_id, agora):
        if org_id == msps.org_a.pk:
            raise RuntimeError("falha simulada")
        return original(org_id, agora)

    monkeypatch.setattr(disparo, "disparar_da_organizacao", quebra_no_a)
    assert disparo.disparar_agendamentos(MARCADO + timedelta(minutes=1)) == 1
    assert relatorios_de(msps.org_a) == [] and len(relatorios_de(msps.org_b)) == 1


def test_historico_mostra_que_veio_do_agendamento(msps, entrar_como):
    a = criar(msps.cliente_a, msps.org_a)
    disparar_agendamentos(MARCADO + timedelta(minutes=1))
    with contexto(organizacao_id=msps.org_a.pk):
        a.delete()
    [r] = relatorios_de(msps.org_a)
    assert r.agendamento_id is None and r.origem == Origem.AGENDADO
    html = entrar_como(msps.leitor_a).get(reverse("clientes:detalhe", args=[msps.cliente_a.pk])).content.decode()
    assert "<td>Agendamento</td>" in html


def test_periodica_registrada_no_minuto_1():
    from tarefas import periodicas

    [(nome, hora, minuto, _)] = [p for p in periodicas._periodicas if p[0] == "disparar_agendamentos"]
    assert (hora, minuto) == (None, 1)
