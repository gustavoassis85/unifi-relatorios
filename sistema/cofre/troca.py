"""Troca da chave mestra: regrava todos os valores cifrados com a chave atual.

Roda como o usuário da aplicação, organização por organização (a RLS continua valendo).
"""
from organizacoes.isolamento import contexto
from organizacoes.models import Organizacao

from .cifra import recifrar
from .registro import modelos_cifrados


def recriptografar_tudo():
    """Devolve quantos valores foram regravados."""
    total = 0
    for org_id in Organizacao.objects.values_list("pk", flat=True):
        with contexto(organizacao_id=org_id):
            for modelo in modelos_cifrados():
                for registro in modelo.objects.select_for_update():
                    campos = [c for c in modelo.CAMPOS_CIFRADOS if getattr(registro, c)]
                    for campo in campos:
                        setattr(registro, campo, recifrar(getattr(registro, campo)))
                    if campos:
                        registro.save(update_fields=campos)
                        total += len(campos)
    return total
