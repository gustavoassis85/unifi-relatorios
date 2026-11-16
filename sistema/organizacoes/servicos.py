from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Organizacao, Papel, Vinculo


def vincular(usuario, organizacao, papel):
    """Cria o vínculo. O dono da plataforma nunca pertence a uma organização."""
    if usuario.is_superuser or usuario.is_staff:
        raise ValidationError("O dono da plataforma não pode pertencer a uma organização.")
    return Vinculo.objects.create(usuario=usuario, organizacao=organizacao, papel=papel)


@transaction.atomic
def criar_organizacao_com_admin(nome, admin_email, admin_nome, admin_senha):
    """Usado pelo dono da plataforma: cria a organização e o primeiro admin dela, juntos."""
    organizacao = Organizacao.objects.create(nome=nome.strip())
    usuario = get_user_model().objects.create_user(
        admin_email, admin_senha, nome=admin_nome.strip()
    )
    vincular(usuario, organizacao, Papel.ADMIN)
    return organizacao, usuario
