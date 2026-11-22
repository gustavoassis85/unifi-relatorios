"""Telas de relatório: gerar, histórico, ver, baixar, higiene, papéis e isolamento."""
import pytest
from django.urls import reverse
from django.utils import timezone

from auditoria.models import Acao, EventoOrganizacao
from organizacoes.isolamento import contexto
from relatorios.models import Relatorio
from relatorios.periodos import opcoes
from tarefas.models import Tarefa

pytestmark = pytest.mark.django_db


def gerar(client, cliente, periodo=None):
    periodo = periodo or opcoes()[0][0]
    return client.post(reverse("relatorios_cliente:gerar", args=[cliente.pk]), {"periodo": periodo}, follow=True)


def pronto(org, cliente, html="<html><body>Relatório pronto</body></html>", **extra):
    with contexto(organizacao_id=org.pk):
        return Relatorio.objects.create(
            cliente=cliente, inicio=timezone.now(), fim=timezone.now(), rotulo="Outubro de 2026",
            situacao="pronto", pronto_em=timezone.now(), html=html, pdf=b"%PDF-1.7 teste", **extra)


def detalhe(client, cliente):
    return client.get(reverse("clientes:detalhe", args=[cliente.pk])).content.decode()


def eventos(org, acao):
    with contexto(organizacao_id=org.pk):
        return list(EventoOrganizacao.objects.filter(acao=acao))


# Gerar ------------------------------------------------------------------------------

@pytest.mark.parametrize("quem", ["admin_a", "operador_a"])
def test_gerar_cria_o_relatorio_e_enfileira(msps, entrar_como, quem):
    usuario = getattr(msps, quem)
    html = gerar(entrar_como(usuario), msps.cliente_a).content.decode()
    assert "Relatório na fila." in html and "Gerando…" in html
    assert 'hx-trigger="every 3s"' in html   # o histórico se atualiza sozinho enquanto gera
    with contexto(organizacao_id=msps.org_a.pk):
        (r,) = Relatorio.objects.all()
    assert r.pedido_por == usuario and r.situacao == "gerando" and r.rotulo == opcoes()[0][1]
    assert Tarefa.objects.get(tipo="gerar_relatorio").parametros == {"relatorio_id": r.pk}
    (evento,) = eventos(msps.org_a, Acao.RELATORIO_PEDIDO)
    assert evento.detalhes["relatorio_id"] == r.pk


def test_um_relatorio_gerando_por_vez(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    gerar(client, msps.cliente_a)
    html = gerar(client, msps.cliente_a, "7d").content.decode()
    assert "Já há um relatório deste cliente sendo gerado" in html
    with contexto(organizacao_id=msps.org_a.pk):
        assert Relatorio.objects.count() == 1


def test_periodo_fora_da_lista(msps, entrar_como):
    html = gerar(entrar_como(msps.admin_a), msps.cliente_a, "mes:1999-01").content.decode()
    assert "Escolha um dos períodos da lista." in html
    with contexto(organizacao_id=msps.org_a.pk):
        assert not Relatorio.objects.exists()


def test_leitura_nao_gera(msps, entrar_como):
    client = entrar_como(msps.leitor_a)
    resposta = client.post(reverse("relatorios_cliente:gerar", args=[msps.cliente_a.pk]), {"periodo": "7d"})
    assert resposta.status_code == 403
    assert "Gerar relatório" not in detalhe(client, msps.cliente_a)


def test_gerar_so_por_post(msps, entrar_como):
    url = reverse("relatorios_cliente:gerar", args=[msps.cliente_a.pk])
    assert entrar_como(msps.admin_a).get(url).status_code == 405


# Histórico, ver e baixar -------------------------------------------------------------

def test_historico_e_ver_o_relatorio_com_csp_propria(msps, entrar_como):
    r = pronto(msps.org_a, msps.cliente_a)
    client = entrar_como(msps.leitor_a)   # leitura vê e baixa
    html = detalhe(client, msps.cliente_a)
    assert "Outubro de 2026" in html and "Pronto" in html and 'hx-trigger="every 3s"' not in html
    resposta = client.get(reverse("relatorios_cliente:ver", args=[msps.cliente_a.pk, r.pk]))
    assert resposta.status_code == 200 and b"Relat\xc3\xb3rio pronto" in resposta.content
    csp = resposta["Content-Security-Policy"]
    assert "default-src 'none'" in csp and "script-src" not in csp and "img-src data:" in csp


def test_baixar_pdf_com_nome_de_arquivo_seguro_e_auditoria(msps, entrar_como):
    with contexto(organizacao_id=msps.org_a.pk):
        msps.cliente_a.nome = 'Padaria "São João"/../x'
        msps.cliente_a.save()
    r = pronto(msps.org_a, msps.cliente_a)
    resposta = entrar_como(msps.leitor_a).get(reverse("relatorios_cliente:baixar", args=[msps.cliente_a.pk, r.pk]))
    assert resposta.status_code == 200 and resposta["Content-Type"] == "application/pdf"
    assert resposta.content == b"%PDF-1.7 teste"
    assert resposta["Content-Disposition"] == (
        'attachment; filename="saude-da-rede-padaria-sao-joao-x-outubro-de-2026.pdf"')
    (evento,) = eventos(msps.org_a, Acao.RELATORIO_BAIXADO)
    assert evento.usuario == msps.leitor_a


@pytest.mark.parametrize("situacao", ["gerando", "falhou"])
def test_relatorio_que_nao_esta_pronto_nao_abre(msps, entrar_como, situacao):
    r = pronto(msps.org_a, msps.cliente_a)
    with contexto(organizacao_id=msps.org_a.pk):
        Relatorio.objects.filter(pk=r.pk).update(situacao=situacao)
    client = entrar_como(msps.admin_a)
    assert client.get(reverse("relatorios_cliente:ver", args=[msps.cliente_a.pk, r.pk])).status_code == 404
    assert client.get(reverse("relatorios_cliente:baixar", args=[msps.cliente_a.pk, r.pk])).status_code == 404


def test_falha_aparece_no_historico(msps, entrar_como):
    r = pronto(msps.org_a, msps.cliente_a)
    with contexto(organizacao_id=msps.org_a.pk):
        Relatorio.objects.filter(pk=r.pk).update(situacao="falhou", erro="Não foi possível gerar o PDF (Timeout).")
    html = detalhe(entrar_como(msps.admin_a), msps.cliente_a)
    assert "Falhou" in html and "Não foi possível gerar o PDF (Timeout)." in html


def test_higiene_da_conta_aparece_so_na_tela_do_msp(msps, entrar_como):
    pronto(msps.org_a, msps.cliente_a, html="<html>relatório do cliente</html>",
           higiene=[{"titulo": "CGU antigo fora do acompanhamento", "evidencia": "desconectado"}])
    client = entrar_como(msps.admin_a)
    assert "CGU antigo fora do acompanhamento" in detalhe(client, msps.cliente_a)


# Isolamento ---------------------------------------------------------------------------

def test_nao_ve_nem_baixa_relatorio_de_outra_organizacao(msps, entrar_como):
    r = pronto(msps.org_b, msps.cliente_b, html="<html>segredo do B</html>")
    client = entrar_como(msps.admin_a)
    for nome in ("ver", "baixar"):
        assert client.get(reverse(f"relatorios_cliente:{nome}", args=[msps.cliente_b.pk, r.pk])).status_code == 404
        # nem trocando o cliente da URL pelo da própria organização
        assert client.get(reverse(f"relatorios_cliente:{nome}", args=[msps.cliente_a.pk, r.pk])).status_code == 404
    assert client.get(reverse("relatorios_cliente:lista", args=[msps.cliente_b.pk])).status_code == 404
    assert client.post(reverse("relatorios_cliente:gerar", args=[msps.cliente_b.pk]), {"periodo": "7d"}).status_code == 404
    assert "segredo do B" not in detalhe(client, msps.cliente_a)
