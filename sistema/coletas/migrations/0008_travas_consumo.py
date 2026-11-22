from django.db import migrations

from organizacoes.rls import travas_de_dado_coletado

TABELAS = [
    "coletas_clienteamostra", "coletas_internetdia", "coletas_internethora", "coletas_clientedia",
    "coletas_aplicativodia", "coletas_naoidentificadodia", "coletas_controlecoleta",
]


class Migration(migrations.Migration):
    dependencies = [("coletas", "0007_consumo")]

    operations = [op for tabela in TABELAS for op in travas_de_dado_coletado(tabela)]
