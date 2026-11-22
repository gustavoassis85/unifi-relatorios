"""Para todo template: em que parte do menu se está e a lista de clientes do painel lateral.

A lista só é calculada se o template usar (objeto preguiçoso): os pedaços que a página
atualiza sozinha (HTMX) não pagam essas consultas.
"""
from django.utils.functional import SimpleLazyObject

from organizacoes import papeis

from .situacao import FILTROS

SECOES = {
    "clientes": "clientes", "conexoes": "clientes", "coletas": "clientes",
    "relatorios_cliente": "clientes", "envios_cliente": "clientes",
    "usuarios": "usuarios", "relatorios": "marca", "envios": "email", "mfa": "conta",
}


def _lista_do_painel():
    from .models import Cliente
    from .situacao import situacao_dos_clientes

    return situacao_dos_clientes(Cliente.objects.all(), completo=False)


def menu_e_painel(request):
    vinculo = getattr(request, "vinculo", None)
    if vinculo is None:
        return {}
    combinacao = getattr(request, "resolver_match", None)
    secao = SECOES.get(combinacao.namespace if combinacao else "", "")
    mostrar = secao == "clientes" and papeis.pode_ver_clientes(vinculo.papel)
    return {
        "secao_menu": secao,
        "mostrar_painel": mostrar,
        "painel_clientes": SimpleLazyObject(_lista_do_painel) if mostrar else [],
        "filtros_painel": FILTROS,
    }
