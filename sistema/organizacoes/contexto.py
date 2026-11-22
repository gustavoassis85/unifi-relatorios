"""Papel do usuário na requisição, a partir do vínculo que o middleware de
contexto já carregou (com a RLS)."""


def papel_da_requisicao(request):
    vinculo = getattr(request, "vinculo", None)
    return vinculo.papel if vinculo else None
