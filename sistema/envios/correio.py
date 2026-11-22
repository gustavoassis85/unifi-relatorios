"""Montar e mandar e-mails pelo SMTP da organização.

Nos testes, ENVIOS_BACKEND aponta para o e-mail em memória do Django: nada sai de verdade.
Os erros viram mensagens em português sem senha, servidor de outro MSP ou destinatários.
"""
import smtplib
import socket
import ssl
from email.utils import formataddr

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.views.decorators.debug import sensitive_variables

from relatorios.servicos import marca_da_organizacao

from .rede import EnderecoProibido

TEMPO_LIMITE = 20


class ErroEnvio(Exception):
    """Falha ao enviar. temporario=True: vale tentar de novo mais tarde."""

    def __init__(self, mensagem, temporario):
        super().__init__(mensagem)
        self.temporario = temporario


@sensitive_variables()
def conexao(config):
    return get_connection(
        settings.ENVIOS_BACKEND,
        host=config.servidor, port=config.porta,
        username=config.usuario or None, password=config.abrir_senha() or None,
        use_tls=config.seguranca == "starttls", use_ssl=config.seguranca == "ssl",
        timeout=TEMPO_LIMITE, fail_silently=False,
    )


def remetente(config):
    nome = " ".join(marca_da_organizacao().empresa.split())
    return formataddr((nome, config.remetente))


def mandar(config, mensagem):
    """Manda uma EmailMessage já montada (sem From). Converte os erros em ErroEnvio."""
    mensagem.from_email = remetente(config)
    try:
        with conexao(config) as con:
            con.send_messages([mensagem])
    except EnderecoProibido as erro:
        raise ErroEnvio(str(erro), temporario=False) from None
    except smtplib.SMTPAuthenticationError:
        raise ErroEnvio("O servidor de e-mail recusou o usuário ou a senha.", temporario=False) from None
    except smtplib.SMTPRecipientsRefused:
        raise ErroEnvio("O servidor de e-mail recusou os destinatários.", temporario=False) from None
    except smtplib.SMTPSenderRefused:
        raise ErroEnvio("O servidor de e-mail recusou o remetente; confira o e-mail do remetente.",
                        temporario=False) from None
    except smtplib.SMTPNotSupportedError:
        raise ErroEnvio("O servidor não aceita a segurança escolhida; confira a porta e a segurança.",
                        temporario=False) from None
    except ssl.SSLCertVerificationError:
        raise ErroEnvio("O certificado do servidor de e-mail não é válido para esse endereço.",
                        temporario=False) from None
    except ssl.SSLError:
        raise ErroEnvio("Falha na conexão segura; confira se a porta combina com a segurança escolhida.",
                        temporario=False) from None
    except (socket.timeout, TimeoutError):
        raise ErroEnvio(f"O servidor de e-mail não respondeu em {TEMPO_LIMITE} s.", temporario=True) from None
    except ConnectionRefusedError:
        raise ErroEnvio("O servidor de e-mail recusou a conexão nessa porta.", temporario=True) from None
    except smtplib.SMTPResponseException as erro:
        temporario = 400 <= erro.smtp_code < 500
        raise ErroEnvio(f"O servidor de e-mail respondeu com o código {erro.smtp_code}.",
                        temporario=temporario) from None
    except (smtplib.SMTPException, OSError) as erro:
        raise ErroEnvio(f"Falha ao falar com o servidor de e-mail ({erro.__class__.__name__}).",
                        temporario=True) from None


def mensagem_de_teste(destinatario):
    return EmailMessage(
        subject="Teste de envio — Dashboard UniFi",
        body=(
            "Este é um e-mail de teste do Dashboard UniFi.\n\n"
            "Se ele chegou, o servidor de e-mail está configurado e os relatórios agendados "
            "podem ser enviados por ele.\n"
        ),
        to=[destinatario],
    )
