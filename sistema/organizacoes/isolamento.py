"""Camada única de isolamento entre MSPs.

1. contexto(...) define a organização (e o usuário) da transação no banco, com
   set_config(..., true) e valores passados como parâmetro. A RLS do PostgreSQL usa isso.
2. ModeloDaOrganizacao: todo modelo com dado de MSP herda dele. As consultas já saem
   filtradas pela organização atual, e gravar em outra organização é recusado.

A RLS é a segunda trava: mesmo que esta camada falhe, o banco não entrega linhas de outro MSP.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import PermissionDenied
from django.db import connection, models, transaction

CHAVE_ORGANIZACAO = "app.organizacao_id"
CHAVE_USUARIO = "app.user_id"

_organizacao_atual = ContextVar("organizacao_atual", default=None)
_NAO_MUDAR = object()


class SemOrganizacao(PermissionDenied):
    """Tentativa de mexer em dado de MSP sem organização definida."""


def organizacao_atual():
    return _organizacao_atual.get()


def exigir_organizacao():
    org = organizacao_atual()
    if org is None:
        raise SemOrganizacao("Nenhuma organização definida.")
    return org


def _como_texto(valor):
    """Só aceita número (ou vazio). Nunca monta SQL com o valor: ele vai como parâmetro."""
    if valor in (None, ""):
        return ""
    return str(int(valor))


def _ler(chave):
    with connection.cursor() as cur:
        cur.execute("select current_setting(%s, true)", [chave])
        return cur.fetchone()[0] or ""


def _gravar(chave, valor):
    with connection.cursor() as cur:
        cur.execute("select set_config(%s, %s, true)", [chave, _como_texto(valor)])


@contextmanager
def contexto(*, organizacao_id=_NAO_MUDAR, usuario_id=_NAO_MUDAR):
    """Define organização e/ou usuário dentro de uma transação e restaura ao sair."""
    mudancas = {}
    if organizacao_id is not _NAO_MUDAR:
        mudancas[CHAVE_ORGANIZACAO] = organizacao_id
    if usuario_id is not _NAO_MUDAR:
        mudancas[CHAVE_USUARIO] = usuario_id

    token = None
    if organizacao_id is not _NAO_MUDAR:
        token = _organizacao_atual.set(int(organizacao_id) if organizacao_id else None)
    try:
        with transaction.atomic():
            anteriores = {chave: _ler(chave) for chave in mudancas}
            for chave, valor in mudancas.items():
                _gravar(chave, valor)
            yield
            # Saída normal: devolve os valores anteriores. Se houve erro ou rollback
            # marcado, o próprio rollback desfaz o set_config.
            if not connection.needs_rollback:
                for chave, valor in anteriores.items():
                    _gravar(chave, valor)
    finally:
        if token is not None:
            _organizacao_atual.reset(token)


class GerenciadorDaOrganizacao(models.Manager):
    def get_queryset(self):
        org = organizacao_atual()
        consulta = super().get_queryset()
        if org is None:
            return consulta.none()
        return consulta.filter(organizacao_id=org)


class ModeloDaOrganizacao(models.Model):
    organizacao = models.ForeignKey(
        "organizacoes.Organizacao",
        on_delete=models.PROTECT,
        related_name="+",
        editable=False,
        verbose_name="organização",
    )

    objects = GerenciadorDaOrganizacao()

    class Meta:
        abstract = True

    def _conferir_organizacao(self):
        org = exigir_organizacao()
        if self.organizacao_id is None:
            self.organizacao_id = org
        elif self.organizacao_id != org:
            raise PermissionDenied("Registro de outra organização.")

    def save(self, *args, **kwargs):
        self._conferir_organizacao()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._conferir_organizacao()
        return super().delete(*args, **kwargs)
