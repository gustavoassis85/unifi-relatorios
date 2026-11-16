from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from .isolamento import contexto, exigir_organizacao
from .models import Organizacao, Papel, Vinculo


def vinculos_da_organizacao():
    """Ponto de partida de toda tela de gestão de usuários: só a organização atual."""
    return Vinculo.objects.filter(organizacao_id=exigir_organizacao()).select_related("usuario")


def vincular(usuario, organizacao, papel):
    """Cria o vínculo. O dono da plataforma nunca pertence a uma organização."""
    if usuario.is_superuser or usuario.is_staff:
        raise ValidationError("O dono da plataforma não pode pertencer a uma organização.")
    return Vinculo.objects.create(usuario=usuario, organizacao=organizacao, papel=papel)


@transaction.atomic
def criar_usuario_na_organizacao(organizacao, email, nome, senha, papel):
    """Usado pelo admin da organização: só cria usuário na organização atual."""
    if organizacao.pk != exigir_organizacao():
        raise PermissionDenied("Organização diferente da atual.")
    usuario = get_user_model().objects.create_user(email, senha, nome=nome.strip())
    vincular(usuario, organizacao, papel)
    return usuario


@transaction.atomic
def criar_organizacao_com_admin(nome, admin_email, admin_nome, admin_senha):
    """Usado pelo dono da plataforma: cria a organização e o primeiro admin dela, juntos.

    O dono não tem organização. Só para gravar o primeiro vínculo, a organização recém-criada
    é definida no banco; ao sair do bloco, o contexto anterior (vazio) volta.
    """
    organizacao = Organizacao.objects.create(nome=nome.strip())
    usuario = get_user_model().objects.create_user(
        admin_email, admin_senha, nome=admin_nome.strip()
    )
    with contexto(organizacao_id=organizacao.pk):
        vincular(usuario, organizacao, Papel.ADMIN)
    return organizacao, usuario
