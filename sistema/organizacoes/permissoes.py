"""Checagem de papel nas telas.

- Sem organização (ex.: dono da plataforma) ou papel sem permissão: 403.
- Registro de outra organização: 404, decidido na busca (a camada de isolamento
  e a RLS simplesmente não encontram a linha).
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from . import papeis


def exige(permissao):
    def decorador(visao):
        @login_required
        @wraps(visao)
        def embrulho(request, *args, **kwargs):
            vinculo = getattr(request, "vinculo", None)
            if vinculo is None or not permissao(vinculo.papel):
                raise PermissionDenied
            return visao(request, *args, **kwargs)

        return embrulho

    return decorador


def para_templates(request):
    """Disponível em todo template: organização e o que o usuário pode fazer."""
    vinculo = getattr(request, "vinculo", None)
    papel = vinculo.papel if vinculo else None
    return {
        "vinculo": vinculo,
        "pode_editar_clientes": papeis.pode_editar_clientes(papel),
        "pode_gerenciar_usuarios": papeis.pode_gerenciar_usuarios(papel),
    }
