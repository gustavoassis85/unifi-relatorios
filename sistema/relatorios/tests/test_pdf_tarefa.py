"""PDF com o Chromium travado, tarefa de geração, períodos e retenção."""
import threading
from datetime import datetime, timedelta, timezone as tz
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from django.db import connection

from organizacoes.isolamento import contexto
from relatorios import pdf as modulo_pdf
from relatorios import tarefas as tarefa_relatorio
from relatorios.models import Relatorio
from relatorios.pdf import ErroPdf, _abrir, gerar_pdf
from relatorios.periodos import PeriodoInvalido, opcoes, resolver
from tarefas.fila import executar, pegar_proxima
from tarefas.models import Situacao, Tarefa

PIXEL = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQ"
         "AAAABJRU5ErkJggg==")


# Chromium travado (usa o Chromium de verdade) ---------------------------------------------

def test_gera_pdf_de_verdade():
    pdf = gerar_pdf("<html><body><h1>Relatório</h1></body></html>")
    assert pdf.startswith(b"%PDF-") and len(pdf) > 500


def test_javascript_desligado_e_arquivo_local_bloqueado(tmp_path):
    arquivo = tmp_path / "segredo.png"
    arquivo.write_bytes(bytes.fromhex("89504e470d0a1a0a"))
    html = (f'<html><head><title>original</title><script>document.title="JS rodou"</script></head><body>'
            f'<img id="local" src="{arquivo.as_uri()}"><img id="embutida" src="{PIXEL}"></body></html>')
    titulo, larguras = _abrir(html, lambda p: (
        p.title(), p.evaluate('["local", "embutida"].map(i => document.getElementById(i).naturalWidth)')))
    assert titulo == "original"
    assert larguras == [0, 1]   # arquivo local não carrega; imagem embutida sim


def test_nenhum_acesso_a_rede():
    pedidos = []

    class Registrar(BaseHTTPRequestHandler):
        def do_GET(self):
            pedidos.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    servidor = HTTPServer(("127.0.0.1", 0), Registrar)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    endereco = f"http://127.0.0.1:{servidor.server_port}"
    try:
        gerar_pdf(f'<html><head><link rel="stylesheet" href="{endereco}/estilo.css"></head>'
                  f'<body><img src="{endereco}/rastreio.png"><iframe src="{endereco}/pagina"></iframe></body></html>')
    finally:
        servidor.shutdown()
    assert pedidos == []


def test_falha_do_chromium_vira_mensagem(monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))  # pasta sem Chromium
    with pytest.raises(ErroPdf) as erro:
        gerar_pdf("<html></html>")
    assert str(erro.value) == "Não foi possível gerar o PDF (o Chromium não está instalado no servidor)."
    assert str(tmp_path) not in str(erro.value)   # caminho do servidor não vai para a tela


# Períodos ------------------------------------------------------------------------------

AGORA = datetime(2026, 11, 21, 15, 0, tzinfo=tz.utc)


def test_opcoes_comecam_pelo_mes_anterior():
    lista = opcoes(AGORA)
    assert lista[:3] == [("mes:2026-10", "Outubro de 2026"), ("30d", "Últimos 30 dias"), ("7d", "Últimos 7 dias")]
    assert lista[-1] == ("mes:2025-10", "Outubro de 2025") and len(lista) == 15


def test_mes_fechado_no_horario_de_brasilia():
    inicio, fim, rotulo = resolver("mes:2026-10", AGORA)
    assert rotulo == "Outubro de 2026"
    assert inicio == datetime(2026, 10, 1, 3, 0, tzinfo=tz.utc)
    assert fim == datetime(2026, 11, 1, 2, 59, 59, tzinfo=tz.utc)


def test_ultimos_dias():
    inicio, fim, rotulo = resolver("7d", AGORA)
    assert (fim - inicio, rotulo) == (timedelta(days=7), "Últimos 7 dias")


@pytest.mark.parametrize("valor", ["mes:2026-11", "mes:2020-01", "mes:2026-13", "90d", "", "mes:2026-1"])
def test_periodo_fora_da_lista_e_recusado(valor):
    with pytest.raises(PeriodoInvalido):
        resolver(valor, AGORA)


# Tarefa de geração ----------------------------------------------------------------------

def pedir(org, cliente, usuario=None):
    with contexto(organizacao_id=org.pk):
        inicio, fim, rotulo = resolver("7d")
        relatorio = Relatorio.objects.create(cliente=cliente, inicio=inicio, fim=fim, rotulo=rotulo, pedido_por=usuario)
    tarefa_relatorio.enfileirar_relatorio(relatorio)
    return relatorio


def recarregar(org, relatorio):
    with contexto(organizacao_id=org.pk):
        return Relatorio.objects.get(pk=relatorio.pk)


@pytest.mark.django_db
def test_tarefa_gera_html_e_pdf(msps):
    relatorio = pedir(msps.org_a, msps.cliente_a, msps.admin_a)
    executar(pegar_proxima())
    r = recarregar(msps.org_a, relatorio)
    assert r.situacao == "pronto" and r.pronto_em and r.erro == ""
    assert "Saúde da rede · Padaria do A" in r.html
    assert bytes(r.pdf).startswith(b"%PDF-")


@pytest.mark.django_db
def test_falha_no_pdf_fica_no_historico_e_nao_repete(msps, monkeypatch):
    def quebra(html):
        raise ErroPdf("Não foi possível gerar o PDF (Timeout 60000ms exceeded).")

    monkeypatch.setattr(tarefa_relatorio, "gerar_pdf", quebra)
    relatorio = pedir(msps.org_a, msps.cliente_a)
    executar(pegar_proxima())
    r = recarregar(msps.org_a, relatorio)
    assert r.situacao == "falhou" and "Timeout" in r.erro and r.pdf is None
    assert Tarefa.objects.get(tipo="gerar_relatorio").situacao == Situacao.FALHOU


@pytest.mark.django_db
def test_erro_inesperado_guarda_so_o_tipo(msps, monkeypatch):
    def quebra(cliente, inicio, fim):
        raise KeyError("detalhe-interno")

    monkeypatch.setattr(tarefa_relatorio, "montar", quebra)
    relatorio = pedir(msps.org_a, msps.cliente_a)
    executar(pegar_proxima())
    r = recarregar(msps.org_a, relatorio)
    assert r.erro == "Erro inesperado ao montar o relatório (KeyError)."


@pytest.mark.django_db
def test_relatorios_isolados_por_organizacao(msps):
    pedir(msps.org_a, msps.cliente_a)
    pedir(msps.org_b, msps.cliente_b)
    with contexto(organizacao_id=msps.org_a.pk):
        assert [r.cliente_id for r in Relatorio.objects.all()] == [msps.cliente_a.pk]
    with connection.cursor() as cur:
        cur.execute("select relrowsecurity, relforcerowsecurity from pg_class where relname = 'relatorios_relatorio'")
        assert cur.fetchone() == (True, True)
        cur.execute("select count(*) from relatorios_relatorio")
        assert cur.fetchone() == (0,)


@pytest.mark.django_db
def test_retencao_apaga_relatorios_com_mais_de_13_meses(msps):
    antigo, novo = pedir(msps.org_a, msps.cliente_a), pedir(msps.org_b, msps.cliente_b)
    agora = datetime.now(tz.utc)
    for org, r, dias in ((msps.org_a, antigo, 400), (msps.org_b, novo, 300)):
        with contexto(organizacao_id=org.pk):
            Relatorio.objects.filter(pk=r.pk).update(pedido_em=agora - timedelta(days=dias))
    assert tarefa_relatorio.apagar_relatorios_antigos(agora) == 1
    with contexto(organizacao_id=msps.org_b.pk):
        assert Relatorio.objects.filter(pk=novo.pk).exists()


def test_pasta_dos_navegadores_fica_no_projeto():
    assert modulo_pdf.PASTA_NAVEGADORES.name == ".navegadores"
