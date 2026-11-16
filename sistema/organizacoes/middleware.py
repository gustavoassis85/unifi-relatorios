from django.db import transaction

from .isolamento import contexto
from .models import Vinculo


class ContextoOrganizacaoMiddleware:
    """Define, para cada requisição, o usuário e a organização no banco.

    A organização vem só do vínculo do usuário logado (id da sessão, guardada no
    servidor). Nada vindo da tela, da URL ou de cookie escolhe a organização.
    A requisição inteira roda numa transação; ao fim, os valores somem.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.vinculo = None
        usuario = request.user
        if not usuario.is_authenticated:
            return self.get_response(request)

        with transaction.atomic(), contexto(usuario_id=usuario.pk):
            # A RLS do vínculo deixa ver a própria linha só com o usuário definido.
            vinculo = (
                Vinculo.objects.select_related("organizacao").filter(usuario_id=usuario.pk).first()
            )
            if vinculo and vinculo.organizacao.ativa:
                request.vinculo = vinculo
            org_id = request.vinculo.organizacao_id if request.vinculo else None

            with contexto(organizacao_id=org_id):
                resposta = self.get_response(request)
                if resposta.status_code >= 500:
                    # Erro no meio da requisição: nada do que ela gravou fica no banco.
                    transaction.set_rollback(True)
        return resposta
