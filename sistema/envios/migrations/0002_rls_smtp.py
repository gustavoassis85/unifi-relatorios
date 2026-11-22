from django.db import migrations

from organizacoes.rls import rls_por_organizacao


class Migration(migrations.Migration):
    dependencies = [("envios", "0001_initial")]

    operations = [rls_por_organizacao("envios_configsmtp")]
