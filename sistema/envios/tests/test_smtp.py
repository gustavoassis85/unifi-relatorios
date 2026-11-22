"""SMTP da organização: tela, senha cifrada, papéis, isolamento, envio de teste e rede interna."""
import smtplib
import socket

import pytest
from django.core import mail
from django.db import connection
from django.urls import reverse

from auditoria.models import Acao, EventoOrganizacao
from envios import correio, rede
from envios.models import ConfigSmtp
from organizacoes.isolamento import contexto
from tarefas.fila import executar, pegar_proxima

pytestmark = pytest.mark.django_db

URL = "envios:smtp"
SENHA = "senha-de-app-abcd1234"


@pytest.fixture(autouse=True)
def email_em_memoria(settings):
    settings.ENVIOS_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


def dados(**extra):
    return {"ativo": "on", "servidor": "smtp.exemplo.com.br", "porta": "587", "seguranca": "starttls",
            "usuario": "relatorios@exemplo.com.br", "senha": SENHA, "remetente": "relatorios@exemplo.com.br",
            **extra}


def salvar(client, **extra):
    return client.post(reverse(URL), dados(**extra), follow=True)


def config_de(org):
    with contexto(organizacao_id=org.pk):
        return ConfigSmtp.objects.first()


def rodar_fila():
    while (t := pegar_proxima()) is not None:
        executar(t)


def test_admin_salva_e_a_senha_fica_cifrada(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    html = salvar(client).content.decode()
    assert "Servidor de e-mail salvo." in html
    config = config_de(msps.org_a)
    assert SENHA not in config.senha_cifrada and config.abrir_senha() == SENHA
    assert config.final == "1234"
    assert SENHA not in html and "termina em 1234" in html
    with contexto(organizacao_id=msps.org_a.pk):
        evento = EventoOrganizacao.objects.get(acao=Acao.SMTP_ALTERADO)
    assert evento.detalhes["servidor"] == "smtp.exemplo.com.br"
    assert SENHA not in str(evento.detalhes)


def test_senha_em_branco_mantem_a_atual(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    salvar(client)
    salvar(client, senha="", servidor="smtp2.exemplo.com.br")
    config = config_de(msps.org_a)
    assert config.servidor == "smtp2.exemplo.com.br" and config.abrir_senha() == SENHA


def test_usuario_sem_senha_e_recusado(msps, entrar_como):
    html = salvar(entrar_como(msps.admin_a), senha="").content.decode()
    assert "Com usuário, informe também a senha." in html
    assert config_de(msps.org_a) is None


@pytest.mark.parametrize("servidor", ["localhost", "127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254",
                                      "[::1]", "http://smtp.x.com", "smtp.x.com:587", "a b.com"])
def test_servidor_interno_ou_mal_escrito_e_recusado(msps, entrar_como, servidor):
    salvar(entrar_como(msps.admin_a), servidor=servidor)
    assert config_de(msps.org_a) is None


def test_porta_fora_da_lista_e_recusada(msps, entrar_como):
    salvar(entrar_como(msps.admin_a), porta="22")
    assert config_de(msps.org_a) is None


def test_sem_criptografia_nao_e_opcao(msps, entrar_como):
    salvar(entrar_como(msps.admin_a), seguranca="nenhuma")
    assert config_de(msps.org_a) is None


@pytest.mark.parametrize("quem", ["operador_a", "leitor_a"])
def test_so_admin_mexe_no_smtp(msps, entrar_como, quem):
    client = entrar_como(getattr(msps, quem))
    for nome in (URL, "envios:situacao_teste"):
        assert client.get(reverse(nome)).status_code == 403
    assert client.post(reverse(URL), dados()).status_code == 403
    assert client.post(reverse("envios:testar")).status_code == 403
    assert reverse(URL) not in client.get(reverse("clientes:lista")).content.decode()


def test_cada_organizacao_tem_o_seu_smtp(msps, entrar_como):
    salvar(entrar_como(msps.admin_b), servidor="smtp.do-b.com")
    html = entrar_como(msps.admin_a).get(reverse(URL)).content.decode()
    assert "smtp.do-b.com" not in html and "termina em" not in html
    salvar(entrar_como(msps.admin_a), servidor="smtp.do-a.com")
    assert config_de(msps.org_a).servidor == "smtp.do-a.com"
    assert config_de(msps.org_b).servidor == "smtp.do-b.com"
    with connection.cursor() as cur:
        cur.execute("select relrowsecurity, relforcerowsecurity from pg_class where relname = 'envios_configsmtp'")
        assert cur.fetchone() == (True, True)
        cur.execute("select count(*) from envios_configsmtp")
        assert cur.fetchone() == (0,)


def test_envio_de_teste_pelo_trabalhador(msps, entrar_como):
    client = entrar_como(msps.admin_a)
    salvar(client)
    client.post(reverse("envios:testar"))
    assert config_de(msps.org_a).teste_pendente
    assert "Enviando o e-mail de teste" in client.get(reverse("envios:situacao_teste")).content.decode()
    rodar_fila()
    assert len(mail.outbox) == 1
    enviado = mail.outbox[0]
    assert enviado.to == ["admin@a.com"]
    assert enviado.from_email == "MSP A <relatorios@exemplo.com.br>"
    config = config_de(msps.org_a)
    assert config.teste_ok and not config.teste_pendente
    assert "E-mail de teste enviado" in client.get(reverse(URL)).content.decode()
    with contexto(organizacao_id=msps.org_a.pk):
        assert EventoOrganizacao.objects.filter(acao=Acao.SMTP_TESTADO).count() == 1


def test_teste_que_falha_mostra_o_motivo(msps, entrar_como, monkeypatch):
    def recusa(*args, **kwargs):
        raise smtplib.SMTPAuthenticationError(535, b"bad")

    monkeypatch.setattr(mail.backends.locmem.EmailBackend, "send_messages", recusa)
    client = entrar_como(msps.admin_a)
    salvar(client)
    client.post(reverse("envios:testar"))
    rodar_fila()
    config = config_de(msps.org_a)
    assert config.teste_ok is False
    assert config.teste_resultado == "O servidor de e-mail recusou o usuário ou a senha."


def test_conexao_recusa_ip_interno_mesmo_vindo_do_dns(monkeypatch):
    """O formulário não resolve o nome; quem barra o DNS que aponta para dentro é a conexão."""
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 587))])
    abertas = []
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: abertas.append(a))
    with pytest.raises(rede.EnderecoProibido):
        rede.SMTPSoInternet("smtp.parece-publico.com", 587, timeout=1)
    assert abertas == []


def test_conexao_vai_para_o_ip_conferido(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 587))])
    abertas = []

    def conectar(endereco, *a, **k):
        abertas.append(endereco)
        raise ConnectionRefusedError

    monkeypatch.setattr(socket, "create_connection", conectar)
    with pytest.raises(ConnectionRefusedError):
        rede.SMTPSoInternet("smtp.publico.com", 587, timeout=1)
    assert abertas == [("8.8.8.8", 587)]


@pytest.mark.parametrize("ip, publico", [("8.8.8.8", True), ("10.0.0.1", False), ("172.16.0.1", False),
                                         ("100.64.0.1", False), ("127.0.0.1", False), ("::1", False),
                                         ("::ffff:192.168.0.1", False), ("fe80::1", False), ("224.0.0.1", False)])
def test_ip_publico(ip, publico):
    assert rede.ip_publico(ip) is publico


def test_backend_padrao_e_o_que_so_sai_para_a_internet():
    from config import settings as configuracao
    assert configuracao.ENVIOS_BACKEND == "envios.rede.BackendSoInternet"
    assert configuracao.ENVIOS_PERMITIR_REDE_INTERNA is False
    assert rede.BackendSoInternet(use_ssl=True).connection_class is rede.SMTPSSLSoInternet
    assert rede.BackendSoInternet(use_tls=True).connection_class is rede.SMTPSoInternet
    assert correio.TEMPO_LIMITE == 20
