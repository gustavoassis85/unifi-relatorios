from django.db import migrations

from organizacoes.rls import cliente_da_mesma_organizacao, rls_por_organizacao


class Migration(migrations.Migration):
    dependencies = [("relatorios", "0003_relatorio")]

    operations = [
        rls_por_organizacao("relatorios_relatorio"),
        cliente_da_mesma_organizacao("relatorios_relatorio"),
    ]
