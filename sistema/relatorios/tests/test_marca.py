"""Marca da organização: tela, validação do logo, papéis e isolamento."""
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.urls import reverse
from PIL import Image

from auditoria.models import Acao, EventoOrganizacao
from organizacoes.isolamento import contexto
from relatorios.models import Marca

pytestmark = pytest.mark.django_db

URL = "relatorios:marca"


def imagem(formato="PNG", tamanho=(1200, 400), extra=b""):
    saida = io.BytesIO()
    Image.new("RGB", tamanho, (0, 111, 255)).save(saida, format=formato)
    return saida.getvalue() + extra


def arquivo(nome, dados, tipo="image/png"):
    return SimpleUploadedFile(nome, dados, content_type=tipo)


def salvar(client, **extra):
    dados = {"empresa": "  Rede   Boa TI ", "contato": "suporte@redeboa.com.br", "tema": "claro", **extra}
    return client.post(reverse(URL), dados, follow=True)


def marca_de(org):
    with contexto(organizacao_id=org.pk):
        return Marca.objects.first()


def test_sem_marca_usa_o_nome_da_organizacao(msps, entrar_como):
    html = entrar_como(msps.admin_a).get(reverse(URL)).content.decode()
    assert 'value="MSP A"' in html


def test_admin_salva_a_marca_com_logo_png(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    html = salvar(client, logo_arquivo=arquivo("logo.png", imagem())).content.decode()
    assert "Marca salva." in html
    marca = marca_de(msps.org_a)
    assert (marca.empresa, marca.contato, marca.tema) == ("Rede Boa TI", "suporte@redeboa.com.br", "claro")
    with Image.open(io.BytesIO(bytes(marca.logo))) as logo:
        assert logo.format == "PNG" and logo.size == (600, 200)  # reduzido para caber em 600 x 200
    assert "data:image/png;base64," in html  # prévia na tela
    with contexto(organizacao_id=msps.org_a.pk):
        (evento,) = EventoOrganizacao.objects.filter(acao=Acao.MARCA_ALTERADA)
    assert evento.detalhes == {"empresa": "Rede Boa TI", "tema": "claro", "logo": True}


def test_jpg_vira_png(msps, entrar_como):
    salvar(entrar_como(msps.admin_a), logo_arquivo=arquivo("logo.jpg", imagem("JPEG"), "image/jpeg"))
    assert bytes(marca_de(msps.org_a).logo).startswith(b"\x89PNG")


def test_conteudo_escondido_no_fim_do_arquivo_e_descartado(msps, entrar_como):
    disfarcado = imagem(tamanho=(100, 50), extra=b"<script>alert(1)</script>")
    salvar(entrar_como(msps.admin_a), logo_arquivo=arquivo("logo.png", disfarcado))
    assert b"<script>" not in bytes(marca_de(msps.org_a).logo)


@pytest.mark.parametrize("nome,dados,mensagem", [
    ("logo.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "Envie o logo em PNG ou JPG."),
    ("logo.png", b"isto nao e uma imagem", "Envie o logo em PNG ou JPG."),
    ("logo.png", b"\x89PNG\r\n\x1a\n" + b"lixo" * 50, "Não foi possível abrir a imagem."),
    ("logo.png", imagem("GIF"), "Envie o logo em PNG ou JPG."),
    ("logo.png", imagem(extra=b"0" * 600 * 1024), "no máximo 500 KB"),
])
def test_logos_recusados(msps, entrar_como, nome, dados, mensagem):
    html = salvar(entrar_como(msps.admin_a), logo_arquivo=arquivo(nome, dados)).content.decode()
    assert mensagem in html
    assert marca_de(msps.org_a) is None


def test_remover_logo(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    salvar(client, logo_arquivo=arquivo("logo.png", imagem()))
    salvar(client, remover_logo="on")
    assert marca_de(msps.org_a).logo is None


def test_trocar_dados_sem_mandar_logo_mantem_o_logo(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    salvar(client, logo_arquivo=arquivo("logo.png", imagem()))
    salvar(client, empresa="Outro Nome")
    marca = marca_de(msps.org_a)
    assert marca.empresa == "Outro Nome" and marca.logo


@pytest.mark.parametrize("quem", ["operador_a", "leitor_a"])
def test_so_admin_edita_a_marca(msps, entrar_como, quem):
    client = entrar_como(getattr(msps, quem))
    assert client.get(reverse(URL)).status_code == 403
    assert client.post(reverse(URL), {"empresa": "x", "tema": "claro"}).status_code == 403
    assert reverse(URL) not in client.get(reverse("clientes:lista")).content.decode()


def test_cada_organizacao_tem_a_sua_marca(msps, entrar_como):
    salvar(entrar_como(msps.admin_b), empresa="Marca do B", logo_arquivo=arquivo("logo.png", imagem()))
    html = entrar_como(msps.admin_a).get(reverse(URL)).content.decode()
    assert "Marca do B" not in html and "data:image/png" not in html
    salvar(entrar_como(msps.admin_a), empresa="Marca do A")
    assert marca_de(msps.org_a).empresa == "Marca do A"
    assert marca_de(msps.org_b).empresa == "Marca do B"
    with connection.cursor() as cur:
        cur.execute("select relrowsecurity, relforcerowsecurity from pg_class where relname = 'relatorios_marca'")
        assert cur.fetchone() == (True, True)
        cur.execute("select count(*) from relatorios_marca")
        assert cur.fetchone() == (0,)
