from django.db import migrations

from organizacoes.rls import cliente_da_mesma_organizacao, rls_por_organizacao


class Migration(migrations.Migration):
    dependencies = [("conexoes", "0003_teste_e_consoles")]

    operations = [
        rls_por_organizacao("conexoes_console"),
        cliente_da_mesma_organizacao("conexoes_console"),
    ]
