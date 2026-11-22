from django.db import migrations

from organizacoes.rls import cliente_da_mesma_organizacao, rls_por_organizacao


class Migration(migrations.Migration):
    dependencies = [("envios", "0003_agendamento")]

    operations = [
        rls_por_organizacao("envios_agendamento"),
        cliente_da_mesma_organizacao("envios_agendamento"),
    ]
