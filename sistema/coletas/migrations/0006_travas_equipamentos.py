from django.db import migrations

from organizacoes.rls import travas_de_dado_coletado

TABELAS = [
    "coletas_sitenetwork", "coletas_clientesamostra", "coletas_equipamentoamostra",
    "coletas_radioamostra", "coletas_radioconfig", "coletas_portaestado",
]


class Migration(migrations.Migration):
    dependencies = [("coletas", "0005_equipamentos")]

    operations = [op for tabela in TABELAS for op in travas_de_dado_coletado(tabela)]
