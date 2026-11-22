"""Agendamentos: cálculo das datas, tela no cliente, validação, papéis e isolamento."""
from datetime import datetime

import pytest
from django.db import connection
from django.urls import reverse

from auditoria.models import Acao, EventoOrganizacao
from envios.agenda import periodo, proxima
from envios.models import Agendamento, Frequencia
from organizacoes.isolamento import contexto
from relatorios.periodos import FUSO

pytestmark = pytest.mark.django_db


def sp(*args):
    return datetime(*args, tzinfo=FUSO)


def mensal(dia=1, hora=8):
    return Agendamento(frequencia=Frequencia.MENSAL, dia_do_mes=dia, hora=hora)


def semanal(dia=0, hora=8):
    return Agendamento(frequencia=Frequencia.SEMANAL, dia_da_semana=dia, hora=hora)


# --- datas -----------------------------------------------------------------

@pytest.mark.parametrize("agora, esperado", [
    (sp(2026, 11, 22, 10), sp(2026, 12, 1, 8)),      # já passou neste mês
    (sp(2026, 12, 1, 7, 59), sp(2026, 12, 1, 8)),    # ainda hoje
    (sp(2026, 12, 1, 8), sp(2027, 1, 1, 8)),         # na hora exata: a próxima é a seguinte
    (sp(2026, 12, 15), sp(2027, 1, 1, 8)),           # virada de ano
])
def test_proxima_mensal(agora, esperado):
    assert proxima(mensal(), agora) == esperado


def test_mensal_dia_28_em_fevereiro():
    assert proxima(mensal(dia=28, hora=23), sp(2027, 2, 1)) == sp(2027, 2, 28, 23)


@pytest.mark.parametrize("agora, esperado", [
    (sp(2026, 11, 22, 10), sp(2026, 11, 23, 8)),     # domingo -> segunda
    (sp(2026, 11, 23, 7), sp(2026, 11, 23, 8)),      # segunda antes da hora
    (sp(2026, 11, 23, 8), sp(2026, 11, 30, 8)),      # segunda na hora -> semana seguinte
    (sp(2026, 12, 29), sp(2027, 1, 4, 8)),           # virada de ano
])
def test_proxima_semanal(agora, esperado):
    assert proxima(semanal(dia=0), agora) == esperado


def test_trabalhador_parado_por_dias_roda_uma_vez_so():
    """Perdeu três segundas: a próxima é calculada a partir de agora, não das datas perdidas."""
    assert proxima(semanal(dia=0), sp(2026, 12, 24, 15)) == sp(2026, 12, 28, 8)


def test_periodo_mensal_cobre_o_mes_anterior_inteiro():
    inicio, fim, rotulo = periodo(mensal(), sp(2027, 1, 1, 8))
    assert (inicio, fim, rotulo) == (sp(2026, 12, 1), sp(2026, 12, 31, 23, 59, 59), "Dezembro de 2026")


def test_periodo_semanal_cobre_7_dias():
    quando = sp(2026, 11, 23, 8)
    inicio, fim, rotulo = periodo(semanal(), quando)
    assert (fim - inicio).days == 7 and fim == quando and rotulo == "Últimos 7 dias"


# --- telas -----------------------------------------------------------------

def novo(client, cliente, **extra):
    dados = {"frequencia": "mensal", "dia_do_mes": "5", "dia_da_semana": "", "hora": "9",
             "destinatarios_texto": "dono@padaria.com.br\nfinanceiro@padaria.com.br", **extra}
    return client.post(reverse("envios_cliente:novo", args=[cliente.pk]), dados, follow=True)


def agendamentos_de(org):
    with contexto(organizacao_id=org.pk):
        return list(Agendamento.objects.all())


def test_operador_cria_agendamento_mensal(msps, entrar_como):
    html = novo(entrar_como(msps.operador_a), msps.cliente_a).content.decode()
    assert "Agendamento criado: Todo dia 5, às 09:00." in html
    [a] = agendamentos_de(msps.org_a)
    assert a.destinatarios == ["dono@padaria.com.br", "financeiro@padaria.com.br"]
    assert a.dia_da_semana is None and a.ativo and a.criado_por == msps.operador_a
    local = a.proxima_execucao.astimezone(FUSO)
    assert (local.day, local.hour, local.minute) == (5, 9, 0)
    assert "dono@padaria.com.br" in html and "Sem servidor de e-mail ativo" in html
    with contexto(organizacao_id=msps.org_a.pk):
        evento = EventoOrganizacao.objects.get(acao=Acao.AGENDAMENTO_CRIADO)
    assert evento.detalhes["destinatarios"] == 2
    assert "padaria.com.br" not in str(evento.detalhes)   # sem os e-mails na auditoria


def test_semanal_limpa_o_dia_do_mes(msps, entrar_como):
    novo(entrar_como(msps.admin_a), msps.cliente_a, frequencia="semanal", dia_da_semana="5")
    [a] = agendamentos_de(msps.org_a)
    assert (a.dia_do_mes, a.dia_da_semana, a.descricao) == (None, 5, "Todo sábado, às 09:00")


def test_sem_destinatarios_e_aceito(msps, entrar_como):
    novo(entrar_como(msps.admin_a), msps.cliente_a, destinatarios_texto="")
    assert agendamentos_de(msps.org_a)[0].destinatarios == []


@pytest.mark.parametrize("extra, erro", [
    ({"destinatarios_texto": "ok@x.com\nnao-e-email"}, "E-mail inválido: nao-e-email"),
    ({"destinatarios_texto": "\n".join(f"p{i}@x.com" for i in range(11))}, "No máximo 10 destinatários."),
    ({"frequencia": "semanal", "dia_da_semana": ""}, "Escolha o dia da semana."),
    ({"dia_do_mes": "31"}, "Faça uma escolha válida"),
    ({"hora": "24"}, "Faça uma escolha válida"),
])
def test_validacao(msps, entrar_como, extra, erro):
    html = novo(entrar_como(msps.admin_a), msps.cliente_a, **extra).content.decode()
    assert erro in html
    assert agendamentos_de(msps.org_a) == []


def test_destinatario_repetido_entra_uma_vez(msps, entrar_como):
    novo(entrar_como(msps.admin_a), msps.cliente_a, destinatarios_texto="a@x.com, A@x.com; b@x.com")
    assert agendamentos_de(msps.org_a)[0].destinatarios == ["a@x.com", "b@x.com"]


def test_no_maximo_5_por_cliente(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    for _ in range(5):
        novo(client, msps.cliente_a)
    html = novo(client, msps.cliente_a).content.decode()
    assert "já tem 5 agendamentos" in html
    assert len(agendamentos_de(msps.org_a)) == 5


def test_editar_pausar_retomar_e_excluir(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    novo(client, msps.cliente_a)
    [a] = agendamentos_de(msps.org_a)
    args = [msps.cliente_a.pk, a.pk]
    client.post(reverse("envios_cliente:editar", args=args),
                {"frequencia": "semanal", "dia_da_semana": "2", "hora": "7", "destinatarios_texto": "x@y.com"})
    [a] = agendamentos_de(msps.org_a)
    assert (a.descricao, a.destinatarios) == ("Toda quarta-feira, às 07:00", ["x@y.com"])
    client.post(reverse("envios_cliente:pausar", args=args), {"ativo": "0"})
    [a] = agendamentos_de(msps.org_a)
    assert not a.ativo and a.proxima_execucao is None
    client.post(reverse("envios_cliente:pausar", args=args), {"ativo": "1"})
    [a] = agendamentos_de(msps.org_a)
    assert a.ativo and a.proxima_execucao.astimezone(FUSO).weekday() == 2
    assert "Excluir o agendamento" in client.get(reverse("envios_cliente:excluir", args=args)).content.decode()
    client.post(reverse("envios_cliente:excluir", args=args))
    assert agendamentos_de(msps.org_a) == []
    with contexto(organizacao_id=msps.org_a.pk):
        acoes = set(EventoOrganizacao.objects.values_list("acao", flat=True))
    assert {Acao.AGENDAMENTO_ALTERADO, Acao.AGENDAMENTO_PAUSADO, Acao.AGENDAMENTO_RETOMADO,
            Acao.AGENDAMENTO_EXCLUIDO} <= acoes


def test_leitura_ve_mas_nao_mexe(msps, entrar_como):
    novo(entrar_como(msps.admin_a), msps.cliente_a)
    [a] = agendamentos_de(msps.org_a)
    client = entrar_como(msps.leitor_a)
    html = client.get(reverse("clientes:detalhe", args=[msps.cliente_a.pk])).content.decode()
    assert "Todo dia 5, às 09:00" in html and "Novo agendamento" not in html and "Pausar" not in html
    args = [msps.cliente_a.pk, a.pk]
    assert client.get(reverse("envios_cliente:novo", args=[msps.cliente_a.pk])).status_code == 403
    for nome in ("editar", "pausar", "excluir"):
        assert client.post(reverse(f"envios_cliente:{nome}", args=args), {"ativo": "0"}).status_code == 403
    assert agendamentos_de(msps.org_a)[0].ativo


def test_msp_a_nao_alcanca_agendamento_do_b(msps, entrar_como):
    novo(entrar_como(msps.admin_b), msps.cliente_b, destinatarios_texto="diretor@escola.com")
    [b] = agendamentos_de(msps.org_b)
    client = entrar_como(msps.admin_a)
    assert client.get(reverse("envios_cliente:novo", args=[msps.cliente_b.pk])).status_code == 404
    for nome in ("editar", "excluir"):
        assert client.get(reverse(f"envios_cliente:{nome}", args=[msps.cliente_b.pk, b.pk])).status_code == 404
        # nem trocando o cliente da URL pelo próprio
        assert client.get(reverse(f"envios_cliente:{nome}", args=[msps.cliente_a.pk, b.pk])).status_code == 404
    assert client.post(reverse("envios_cliente:pausar", args=[msps.cliente_a.pk, b.pk]),
                       {"ativo": "0"}).status_code == 404
    html = client.get(reverse("clientes:detalhe", args=[msps.cliente_a.pk])).content.decode()
    assert "diretor@escola.com" not in html
    assert agendamentos_de(msps.org_a) == [] and agendamentos_de(msps.org_b)[0].ativo
    with connection.cursor() as cur:
        cur.execute("select relrowsecurity, relforcerowsecurity from pg_class where relname = 'envios_agendamento'")
        assert cur.fetchone() == (True, True)
        cur.execute("select count(*) from envios_agendamento")
        assert cur.fetchone() == (0,)
