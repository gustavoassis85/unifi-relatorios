"""Relatório HTML de um cliente: seções, marca, vários consoles, higiene fora e escape."""
from datetime import datetime, timedelta, timezone as tz

import pytest

from coletas import models as m
from conexoes.models import Console
from organizacoes.isolamento import contexto
from relatorios.models import Marca
from relatorios.montagem import montar

pytestmark = pytest.mark.django_db

INICIO = datetime(2026, 11, 1, 3, 0, tzinfo=tz.utc)
FIM = INICIO + timedelta(days=7)
LOGO = bytes.fromhex("89504e470d0a1a0a") + b"logo"


def console_com_dados(org, cliente, host_id, nome, perda=0.0):
    with contexto(organizacao_id=org.pk):
        c = Console.objects.create(cliente=cliente, host_id=host_id, nome=nome, tipo="console",
                                   conectado=True, acompanhar=True)
        m.ConsoleEstado.objects.create(cliente=cliente, console=c, coletado_em=FIM - timedelta(hours=1), nome=nome,
                                       modelo="UniFi Dream Router", tipo="console", conectado=True,
                                       firmware="5.1.19", ultimo_backup=FIM - timedelta(days=1))
        for h in range(48):
            m.WanHora.objects.create(cliente=cliente, console=c, site_id="s", horario=INICIO + timedelta(hours=h),
                                     perda_pct=perda, latencia_media=8.0, latencia_max=20.0, provedor="V.tal")
        return c


def gerar(org, cliente):
    with contexto(organizacao_id=org.pk):
        return montar(cliente, INICIO, FIM)


def test_relatorio_com_secoes_e_marca(msps):
    console_com_dados(msps.org_a, msps.cliente_a, "udr:1", "Dream Router")
    with contexto(organizacao_id=msps.org_a.pk):
        Marca.objects.create(empresa="Rede Boa TI", contato="suporte@redeboa.com.br", tema="claro", logo=LOGO)
    r = gerar(msps.org_a, msps.cliente_a)
    assert r.erros == []
    for trecho in ("Saúde da rede · Padaria do A", "01/11/2026 a 08/11/2026", "Saúde do link", "Dream Router",
                   "Relatório preparado por Rede Boa TI", "suporte@redeboa.com.br", 'class="tema-claro"',
                   'src="data:image/png;base64,'):
        assert trecho in r.html, trecho
    assert "<script" not in r.html


def test_sem_marca_usa_o_nome_da_organizacao_e_tema_escuro(msps):
    console_com_dados(msps.org_a, msps.cliente_a, "udr:1", "Dream Router")
    r = gerar(msps.org_a, msps.cliente_a)
    assert '<span class="marca">MSP A</span>' in r.html and 'class="tema-escuro"' in r.html


def test_uma_secao_por_console_com_os_achados_de_cada_um(msps):
    console_com_dados(msps.org_a, msps.cliente_a, "udr:1", "Matriz")
    console_com_dados(msps.org_a, msps.cliente_a, "ucg:2", "Filial", perda=4.0)
    r = gerar(msps.org_a, msps.cliente_a)
    assert r.html.count('class="console-secao"') == 2
    matriz, filial = r.html.split('class="console-secao"')[1:]
    if "Filial" in matriz:
        matriz, filial = filial, matriz
    assert "Perda de pacote acima do normal" in filial
    assert "Perda de pacote acima do normal" not in matriz


def test_higiene_da_conta_nao_entra_no_relatorio(msps):
    console_com_dados(msps.org_a, msps.cliente_a, "udr:1", "Dream Router")
    with contexto(organizacao_id=msps.org_a.pk):
        Console.objects.create(cliente=msps.cliente_a, host_id="velho:9", nome="CGU antigo", acompanhar=False)
    r = gerar(msps.org_a, msps.cliente_a)
    assert [a.titulo for a in r.higiene] == ["CGU antigo fora do acompanhamento"]
    assert "CGU antigo" not in r.html


def test_cliente_sem_dados(msps):
    r = gerar(msps.org_a, msps.cliente_a)
    assert "Ainda não há dados coletados" in r.html


def test_texto_da_unifi_e_do_msp_nunca_vira_html(msps):
    with contexto(organizacao_id=msps.org_a.pk):
        msps.cliente_a.nome = "<b>Padaria</b>"
        msps.cliente_a.save()
        Marca.objects.create(empresa='"><script>alert(1)</script>', contato="<i>x</i>")
    console_com_dados(msps.org_a, msps.cliente_a, "udr:1", "<img src=x onerror=alert(1)>")
    r = gerar(msps.org_a, msps.cliente_a)
    assert "<script>" not in r.html and "<img src=x" not in r.html and "<b>Padaria" not in r.html
    assert "&lt;img src=x onerror=alert(1)&gt;" in r.html


def test_dados_de_outra_organizacao_nao_aparecem(msps):
    console_com_dados(msps.org_b, msps.cliente_b, "udr:1", "Console da Escola")
    with contexto(organizacao_id=msps.org_b.pk):
        Marca.objects.create(empresa="Marca do B")
    console_com_dados(msps.org_a, msps.cliente_a, "udr:1", "Dream Router")
    r = gerar(msps.org_a, msps.cliente_a)
    assert "Console da Escola" not in r.html and "Marca do B" not in r.html
