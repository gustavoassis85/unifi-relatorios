"""De qual organização é a requisição, e com qual papel.

Parte 3: lê o vínculo do usuário logado. Na parte 4, isto passa a vir do middleware
que define a organização no banco (RLS).
"""
from .models import Vinculo


def papel_da_requisicao(request):
    if not request.user.is_authenticated:
        return None
    vinculo = Vinculo.objects.filter(usuario_id=request.user.pk).only("papel").first()
    return vinculo.papel if vinculo else None
