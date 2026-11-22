from django.db import migrations

from organizacoes.rls import rls_por_organizacao


class Migration(migrations.Migration):
    dependencies = [("auditoria", "0001_initial")]

    operations = [rls_por_organizacao("auditoria_eventoorganizacao")]
