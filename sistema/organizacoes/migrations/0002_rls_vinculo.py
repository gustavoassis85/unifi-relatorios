from django.db import migrations

from organizacoes.rls import rls_vinculo


class Migration(migrations.Migration):
    dependencies = [("organizacoes", "0001_initial")]

    operations = [rls_vinculo("organizacoes_vinculo")]
