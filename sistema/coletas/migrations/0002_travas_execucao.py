from django.db import migrations

from organizacoes.rls import cliente_da_mesma_organizacao, rls_por_organizacao


class Migration(migrations.Migration):
    dependencies = [("coletas", "0001_initial")]

    operations = [
        rls_por_organizacao("coletas_execucaocoleta"),
        cliente_da_mesma_organizacao("coletas_execucaocoleta"),
    ]
