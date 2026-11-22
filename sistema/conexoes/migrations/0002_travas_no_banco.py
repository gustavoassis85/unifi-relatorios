from django.db import migrations

from organizacoes.rls import cliente_da_mesma_organizacao, rls_por_organizacao


class Migration(migrations.Migration):
    dependencies = [
        ("conexoes", "0001_initial"),
        ("clientes", "0003_cliente_cliente_organizacao_id"),
    ]

    operations = [
        rls_por_organizacao("conexoes_chaveunifi"),
        cliente_da_mesma_organizacao("conexoes_chaveunifi"),
    ]
