from allauth.account.adapter import DefaultAccountAdapter


class AdaptadorContas(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        # Não há cadastro aberto: só o admin da organização ou o dono da plataforma criam usuários.
        return False
