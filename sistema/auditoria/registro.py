"""Ponto único para registrar eventos de auditoria.

Nunca registra senhas, códigos de MFA ou chaves: qualquer detalhe com nome
parecido com isso é descartado antes de gravar.
"""
from organizacoes.isolamento import contexto, organizacao_atual
from organizacoes.models import Vinculo

from .models import EventoOrganizacao, EventoPlataforma

NOMES_PROIBIDOS = ("senha", "password", "codigo", "code", "token", "secret", "segredo", "chave", "key")


def limpar(detalhes):
    return {
        nome: valor
        for nome, valor in detalhes.items()
        if not any(proibido in nome.lower() for proibido in NOMES_PROIBIDOS)
    }


def ip_da_requisicao(request):
    if request is None:
        return None
    # Quando houver um proxy na frente (produção), isto precisa considerar o
    # cabeçalho confiável dele. Por enquanto, o endereço de quem conectou.
    return request.META.get("REMOTE_ADDR") or None


def _usuario(request, usuario):
    if usuario is not None:
        return usuario
    if request is not None and request.user.is_authenticated:
        return request.user
    return None


def registrar(request, acao, usuario=None, **detalhes):
    """Grava na organização atual; sem organização, nos eventos da plataforma."""
    campos = {
        "usuario": _usuario(request, usuario),
        "acao": acao,
        "ip": ip_da_requisicao(request),
        "detalhes": limpar(detalhes),
    }
    if organizacao_atual() is not None:
        return EventoOrganizacao.objects.create(**campos)
    return EventoPlataforma.objects.create(**campos)


def registrar_para_usuario(request, usuario, acao, **detalhes):
    """Para login e falha de login, quando ainda não há organização definida:
    descobre a organização pelo vínculo do próprio usuário (mesmo caminho do middleware)."""
    with contexto(usuario_id=usuario.pk):
        vinculo = Vinculo.objects.filter(usuario_id=usuario.pk).only("organizacao_id").first()
        org_id = vinculo.organizacao_id if vinculo else None
        with contexto(organizacao_id=org_id):
            return registrar(request, acao, usuario=usuario, **detalhes)
