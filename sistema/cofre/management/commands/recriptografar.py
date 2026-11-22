r"""manage.py recriptografar — usado na troca da chave mestra.

1. python scripts\gerar_env.py --trocar-chave-mestra (a atual vira UNIFI_CHAVE_MESTRA_ANTERIOR).
2. Reinicie o sistema e rode este comando.
3. Apague a linha UNIFI_CHAVE_MESTRA_ANTERIOR do .env e reinicie de novo.
"""
from django.core.management.base import BaseCommand

from cofre.troca import recriptografar_tudo


class Command(BaseCommand):
    help = "Regrava todas as credenciais cifradas com a chave mestra atual."

    def handle(self, *args, **opcoes):
        total = recriptografar_tudo()
        self.stdout.write(f"{total} credencial(is) regravada(s) com a chave mestra atual.")
