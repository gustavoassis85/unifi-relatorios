from django.db import migrations

from organizacoes.rls import cliente_da_mesma_organizacao, rls_por_organizacao


class Migration(migrations.Migration):
    dependencies = [("envios", "0005_envio")]

    operations = [
        rls_por_organizacao("envios_envio"),
        cliente_da_mesma_organizacao("envios_envio"),
    ]
