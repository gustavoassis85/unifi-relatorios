from allauth.mfa.models import Authenticator

from organizacoes import papeis


def exige_mfa(usuario, papel):
    """O dono da plataforma e os admins de organização precisam de MFA."""
    return usuario.is_superuser or usuario.is_staff or papeis.exige_mfa(papel)


def tem_mfa(usuario):
    return Authenticator.objects.filter(user_id=usuario.pk, type=Authenticator.Type.TOTP).exists()
