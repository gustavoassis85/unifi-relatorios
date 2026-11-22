"""Conexão SMTP que só sai para a Internet.

O endereço do SMTP é digitado pelo MSP. Com o sistema num servidor, ele não pode servir
para sondar a rede de lá (localhost, IPs privados, link-local, metadados da nuvem).
Por isso o nome é resolvido aqui, todos os IPs são conferidos e a conexão vai para o
IP conferido (não há segunda consulta ao DNS que possa trocar o endereço no meio).
O certificado continua conferido pelo nome do servidor (SNI e verificação do TLS).
"""
import ipaddress
import smtplib
import socket

from django.conf import settings
from django.core.mail.backends.smtp import EmailBackend


class EnderecoProibido(OSError):
    """O servidor aponta para a rede interna. A mensagem pode ir para a tela."""


def ip_publico(ip):
    endereco = ipaddress.ip_address(ip)
    if getattr(endereco, "ipv4_mapped", None):
        endereco = endereco.ipv4_mapped
    return endereco.is_global and not endereco.is_multicast


def eh_ip_literal_interno(texto):
    """Para a validação do formulário: True se o texto já é um IP que não é da Internet."""
    try:
        return not ip_publico(texto.strip("[]"))
    except ValueError:
        return texto.strip().lower().rstrip(".") in ("localhost", "localhost.localdomain") \
            or texto.strip().lower().endswith(".localhost")


def resolver_publico(host, porta):
    """IPs do servidor, todos públicos. Qualquer IP interno recusa o servidor inteiro."""
    if getattr(settings, "ENVIOS_PERMITIR_REDE_INTERNA", False):
        return [info[4][0] for info in socket.getaddrinfo(host, porta, type=socket.SOCK_STREAM)]
    try:
        infos = socket.getaddrinfo(host, porta, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise EnderecoProibido(f"Não foi possível encontrar o servidor {host}.") from None
    ips = list(dict.fromkeys(info[4][0] for info in infos))
    if not ips or not all(ip_publico(ip) for ip in ips):
        raise EnderecoProibido("O servidor de e-mail aponta para uma rede interna; use um endereço da Internet.")
    return ips


class _SoInternet:
    def _get_socket(self, host, port, timeout):
        ultimo = None
        for ip in resolver_publico(host, port):
            try:
                # SMTP_SSL embrulha o socket com server_hostname=self._host (o nome, não o IP).
                return super()._get_socket(ip, port, timeout)
            except OSError as erro:
                ultimo = erro
        raise ultimo


class SMTPSoInternet(_SoInternet, smtplib.SMTP):
    pass


class SMTPSSLSoInternet(_SoInternet, smtplib.SMTP_SSL):
    pass


class BackendSoInternet(EmailBackend):
    """O backend SMTP do Django, com a conexão acima. STARTTLS também confere pelo nome."""

    @property
    def connection_class(self):
        return SMTPSSLSoInternet if self.use_ssl else SMTPSoInternet
