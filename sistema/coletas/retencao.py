"""Por quanto tempo cada dado coletado fica guardado (LGPD: coleta mínima).

- Amostras de hora em hora com detalhe de equipamento ou de dispositivo: 90 dias.
- Tráfego de cada dispositivo por dia (tem o MAC): 90 dias.
- Dados agregados por hora e por dia do site e situação do console: 13 meses, para comparar
  com o mesmo mês do ano anterior.
Uma periódica diária (4h) apaga o que passou do prazo, organização por organização.
"""
import logging
from datetime import timedelta

from organizacoes.isolamento import contexto
from organizacoes.models import Organizacao
from tarefas.periodicas import periodica

from . import models as m

log = logging.getLogger("coletas")

NOVENTA_DIAS = timedelta(days=90)
TREZE_MESES = timedelta(days=396)

# (modelo, campo de data, prazo)
PRAZOS = [
    (m.EquipamentoAmostra, "coletado_em", NOVENTA_DIAS),
    (m.RadioAmostra, "coletado_em", NOVENTA_DIAS),
    (m.RadioConfig, "coletado_em", NOVENTA_DIAS),
    (m.PortaEstado, "coletado_em", NOVENTA_DIAS),
    (m.ClienteAmostra, "coletado_em", NOVENTA_DIAS),
    (m.ClienteDia, "dia", NOVENTA_DIAS),
    (m.ExecucaoColeta, "iniciada_em", NOVENTA_DIAS),
    (m.ConsoleEstado, "coletado_em", TREZE_MESES),
    (m.ClientesAmostra, "coletado_em", TREZE_MESES),
    (m.WanHora, "horario", TREZE_MESES),
    (m.InternetDia, "dia", TREZE_MESES),
    (m.InternetHora, "hora", TREZE_MESES),
    (m.AplicativoDia, "dia", TREZE_MESES),
    (m.NaoIdentificadoDia, "dia", TREZE_MESES),
]


def apagar_dados_antigos(agora):
    """Devolve {nome da tabela: linhas apagadas}."""
    apagadas = {}
    for org_id in Organizacao.objects.values_list("pk", flat=True):
        with contexto(organizacao_id=org_id):
            for modelo, campo, prazo in PRAZOS:
                limite = agora - prazo
                if campo == "dia":
                    limite = limite.date()
                n, _ = modelo.objects.filter(**{f"{campo}__lt": limite}).delete()
                if n:
                    apagadas[modelo._meta.db_table] = apagadas.get(modelo._meta.db_table, 0) + n
    return apagadas


@periodica("apagar_dados_antigos", hora=4, minuto=0)
def apagar_periodicamente(agora):
    apagadas = apagar_dados_antigos(agora)
    log.info("Retenção: %s", apagadas or "nada a apagar")
