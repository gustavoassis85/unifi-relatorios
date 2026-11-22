from django.db import migrations

from organizacoes.rls import travas_de_dado_coletado


class Migration(migrations.Migration):
    dependencies = [
        ("coletas", "0003_consoleestado_wanhora"),
        ("conexoes", "0005_console_console_cliente_id"),
    ]

    operations = [
        *travas_de_dado_coletado("coletas_consoleestado"),
        *travas_de_dado_coletado("coletas_wanhora"),
    ]
