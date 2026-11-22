"""Criptografia das credenciais guardadas no banco (chaves da UniFi, depois senhas de SMTP).

- Fernet (AES-128-CBC + HMAC-SHA256), da biblioteca cryptography.
- A chave mestra vem do ambiente (UNIFI_CHAVE_MESTRA), nunca do banco nem do Git.
- Troca da chave mestra: a nova vai em UNIFI_CHAVE_MESTRA e a antiga em
  UNIFI_CHAVE_MESTRA_ANTERIOR. O sistema lê com as duas e grava só com a nova.
  Depois, manage.py recriptografar regrava tudo com a nova e a antiga pode sair.
- Nenhuma mensagem de erro daqui mostra o texto, o valor cifrado ou a chave mestra.
"""
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.views.decorators.debug import sensitive_variables


class ErroCofre(Exception):
    """Falha ao cifrar ou decifrar (a mensagem nunca contém segredo)."""


def validar_chave_mestra(valor):
    """True se o valor é uma chave Fernet válida (32 bytes em base64 de URL)."""
    try:
        Fernet(valor)
    except (ValueError, TypeError):
        return False
    return True


@sensitive_variables()
def _fernet():
    chaves = [settings.UNIFI_CHAVE_MESTRA] + list(settings.UNIFI_CHAVES_MESTRAS_ANTERIORES)
    return MultiFernet([Fernet(c) for c in chaves])


@sensitive_variables()
def cifrar(texto):
    if not isinstance(texto, str) or not texto:
        raise ErroCofre("Nada para cifrar.")
    return _fernet().encrypt(texto.encode("utf-8")).decode("ascii")


@sensitive_variables()
def decifrar(cifrado):
    try:
        return _fernet().decrypt(cifrado.encode("ascii")).decode("utf-8")
    except (InvalidToken, AttributeError, UnicodeError):
        raise ErroCofre(
            "Não foi possível abrir a credencial guardada. "
            "Confira se a UNIFI_CHAVE_MESTRA é a mesma usada ao salvar."
        ) from None


@sensitive_variables()
def recifrar(cifrado):
    """Regrava o valor com a chave mestra atual (usado na troca da chave mestra)."""
    try:
        return _fernet().rotate(cifrado.encode("ascii")).decode("ascii")
    except (InvalidToken, AttributeError, UnicodeError):
        raise ErroCofre("Valor cifrado inválido ou de outra chave mestra.") from None


def ultimos4(texto):
    """O que pode aparecer na tela depois de salvo."""
    return texto[-4:] if texto and len(texto) >= 8 else ""
