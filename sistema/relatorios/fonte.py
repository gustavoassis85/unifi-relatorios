"""Dados de um cliente para as regras e o relatório, lidos do PostgreSQL.

Entrega as mesmas "linhas" (dicionários) que o banco SQLite do MVP entregava, para que a
lógica das regras e do relatório fique igual à do MVP. Só os consoles acompanhados do
cliente entram. Precisa rodar dentro do contexto da organização (a RLS filtra o resto).
Datas vêm como datetime com fuso (no MVP eram texto).
"""
from collections import defaultdict

from django.db.models import F, Max, Min, Sum

from coletas.models import (
    AplicativoDia, ClienteAmostra, ClienteDia, ConsoleEstado, EquipamentoAmostra, InternetDia, InternetHora,
    NaoIdentificadoDia, PortaEstado, RadioAmostra, RadioConfig, WanHora,
)


class Fonte:
    def __init__(self, cliente, consoles):
        self.cliente = cliente
        self.consoles = list(consoles)
        self.ids = [c.pk for c in self.consoles]

    def _q(self, modelo):
        return modelo.objects.filter(cliente=self.cliente, console_id__in=self.ids).annotate(
            host_id=F("console__host_id"))

    @staticmethod
    def _periodo(consulta, coluna, inicio, fim):
        return consulta.filter(**{f"{coluna}__gte": inicio, f"{coluna}__lte": fim}).order_by(coluna)

    # Link -------------------------------------------------------------------------

    def wan_por_site(self, inicio, fim):
        sites = defaultdict(list)
        for linha in self._periodo(self._q(WanHora), "horario", inicio, fim).values():
            sites[(linha["host_id"], linha["site_id"])].append(linha)
        return sites

    # Consoles ---------------------------------------------------------------------

    def ultimos_consoles(self):
        return list(self._q(ConsoleEstado).order_by("console_id", "-coletado_em").distinct("console_id").values())

    def fotos_consoles(self, inicio, fim):
        return list(self._periodo(self._q(ConsoleEstado), "coletado_em", inicio, fim).values("host_id", "conectado", "tipo"))

    def primeira_vez_com_atualizacao(self, host_id, versao):
        return self._q(ConsoleEstado).filter(host_id=host_id, atualizacao_disponivel=versao).aggregate(
            Min("coletado_em"))["coletado_em__min"]

    # Equipamentos -----------------------------------------------------------------

    def equipamento_amostras(self, inicio, fim):
        return list(self._periodo(self._q(EquipamentoAmostra), "coletado_em", inicio, fim).values())

    def ultimos_equipamentos(self):
        linhas = self._q(EquipamentoAmostra).order_by("device_id", "-coletado_em").distinct("device_id").values()
        return {e["device_id"]: e for e in linhas}

    def portas_ativas(self, inicio, fim):
        return list(self._periodo(self._q(PortaEstado).filter(estado="UP"), "coletado_em", inicio, fim).values())

    def radio_amostras(self, inicio, fim):
        return list(self._periodo(self._q(RadioAmostra), "coletado_em", inicio, fim).values())

    def radios_configurados(self, device_id):
        """Configuração mais recente dos rádios de um equipamento."""
        consulta = self._q(RadioConfig).filter(device_id=device_id)
        ultima = consulta.aggregate(Max("coletado_em"))["coletado_em__max"]
        return list(consulta.filter(coletado_em=ultima).order_by("posicao").values()) if ultima else []

    # Clientes conectados ------------------------------------------------------------

    def amostras_wifi(self, inicio, fim):
        return list(self._periodo(self._q(ClienteAmostra).filter(tipo="WIRELESS"), "coletado_em", inicio, fim).values())

    def amostras_dispositivos(self, inicio, fim):
        return list(self._periodo(self._q(ClienteAmostra), "coletado_em", inicio, fim).values())

    def nome_dispositivo(self, host_id, mac):
        linha = (self._q(ClienteAmostra).filter(host_id=host_id, mac=mac).exclude(nome="")
                 .order_by("-coletado_em").values("nome").first())
        return linha["nome"] if linha else mac

    # Consumo ------------------------------------------------------------------------

    def upload_por_site(self, dia_ini, dia_fim):
        return list(self._q(InternetDia).filter(dia__range=(dia_ini, dia_fim)).values("host_id", "site")
                    .annotate(upload=Sum("upload_bytes")).order_by())

    def maior_upload(self, host_id, site, dia_ini, dia_fim):
        return (self._q(ClienteDia).filter(host_id=host_id, site=site, dia__range=(dia_ini, dia_fim))
                .values("mac").annotate(upload=Sum("upload_bytes"), download=Sum("download_bytes"))
                .order_by("-upload").first())

    def internet_por_dia(self, host_id, dia_ini, dia_fim):
        return list(self._q(InternetDia).filter(host_id=host_id, dia__range=(dia_ini, dia_fim)).values("dia")
                    .annotate(d=Sum("download_bytes"), u=Sum("upload_bytes")).order_by("dia"))

    def internet_por_hora(self, host_id, inicio, fim):
        return list(self._periodo(self._q(InternetHora).filter(host_id=host_id), "hora", inicio, fim).values())

    def aplicativos(self, host_id, dia_ini, dia_fim):
        return list(self._q(AplicativoDia).filter(host_id=host_id, dia__range=(dia_ini, dia_fim))
                    .values("categoria_id", "aplicativo_id")
                    .annotate(d=Sum("download_bytes"), u=Sum("upload_bytes"), disp=Max("dispositivos")).order_by())

    def nao_identificado(self, host_id, dia_ini, dia_fim):
        return list(self._q(NaoIdentificadoDia).filter(host_id=host_id, dia__range=(dia_ini, dia_fim))
                    .values("familia_id").annotate(b=Sum("bytes"), disp=Max("dispositivos")).order_by("-b"))

    def dispositivos_por_dia(self, host_id, dia_ini, dia_fim):
        return list(self._q(ClienteDia).filter(host_id=host_id, dia__range=(dia_ini, dia_fim)).values("mac")
                    .annotate(d=Sum("download_bytes"), u=Sum("upload_bytes")).order_by())
