"""manage.py resumo_cliente <id> [--dias N] — números principais do cliente, no terminal.

Serve para conferir as coletas (comparar com os resumos do MVP) enquanto o relatório
não chega (etapa 4). O id é o número que aparece no endereço da página do cliente
(ex.: /clientes/3/ -> 3). Roda como o usuário da aplicação, no contexto da organização do cliente.
"""
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Avg, Count, Max, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from clientes.models import Cliente
from coletas.catalogo import Nomes
from coletas.models import (
    AplicativoDia, ClienteAmostra, ConsoleEstado, EquipamentoAmostra, ExecucaoColeta, InternetDia, WanHora,
)
from conexoes.models import Console
from organizacoes.isolamento import contexto
from organizacoes.models import Organizacao

SP = ZoneInfo("America/Sao_Paulo")


def gb(valor):
    return f"{(valor or 0) / 1e9:7.2f} GB"


def num(valor, formato="{:.1f}", vazio="—"):
    return formato.format(valor) if valor is not None else vazio


class Command(BaseCommand):
    help = "Mostra os números principais coletados de um cliente."

    def add_arguments(self, parser):
        parser.add_argument("cliente_id", type=int)
        parser.add_argument("--dias", type=int, default=7)

    def handle(self, *args, cliente_id, dias, **opcoes):
        for org in Organizacao.objects.all():
            with contexto(organizacao_id=org.pk):
                cliente = Cliente.objects.filter(pk=cliente_id).first()
                if cliente:
                    self.resumo(org, cliente, dias)
                    return
        raise CommandError(f"Cliente {cliente_id} não encontrado.")

    def linha(self, texto=""):
        self.stdout.write(texto)

    def resumo(self, org, cliente, dias):
        hoje = timezone.localtime(timezone.now(), SP).date()
        inicio = hoje - timedelta(days=dias - 1)
        self.linha(f"Cliente: {cliente.nome} ({org.nome}) — últimos {dias} dias, horário de Brasília")

        self.linha("\nConsoles acompanhados")
        for c in Console.objects.filter(cliente=cliente, acompanhar=True):
            foto = ConsoleEstado.objects.filter(console=c).order_by("-coletado_em").first()
            if foto is None:
                self.linha(f"  {c}: ainda sem coleta")
                continue
            texto = (f"  {foto.nome or c}  {foto.modelo}  {'conectado' if foto.conectado else 'DESCONECTADO'}  "
                     f"firmware {foto.firmware or '—'}  Network {foto.versao_network or '—'}")
            if foto.ultimo_backup:
                texto += f"  backup {timezone.localtime(foto.ultimo_backup, SP):%d/%m %H:%M}"
            self.linha(texto)

        self.linha("\nWAN por dia (hora sem dado = possível indisponibilidade)")
        self.linha("  dia     horas  perda média  perda máx  latência média")
        por_dia = {
            r["dia"]: r for r in WanHora.objects.filter(cliente=cliente, horario__date__gte=inicio - timedelta(days=1))
            .annotate(dia=TruncDate("horario", tzinfo=SP)).values("dia")
            .annotate(horas=Count("id"), perda=Avg("perda_pct"), perda_max=Max("perda_pct"), lat=Avg("latencia_media"))
        }
        for n in range(dias):
            dia = inicio + timedelta(days=n)
            r = por_dia.get(dia, {})
            self.linha(f"  {dia:%d/%m}   {r.get('horas', 0):>3}    {num(r.get('perda'), '{:>6.2f}%')}"
                       f"     {num(r.get('perda_max'), '{:>6.2f}%')}     {num(r.get('lat'), '{:>6.1f} ms')}")

        self.linha("\nInternet por dia")
        self.linha("  dia        download     upload")
        internet = {
            r["dia"]: r for r in InternetDia.objects.filter(cliente=cliente, dia__gte=inicio)
            .values("dia").annotate(d=Sum("download_bytes"), u=Sum("upload_bytes"))
        }
        for n in range(dias):
            dia = inicio + timedelta(days=n)
            r = internet.get(dia)
            self.linha(f"  {dia:%d/%m}   {gb(r['d'])}  {gb(r['u'])}" if r else f"  {dia:%d/%m}   sem dado")

        ultima = EquipamentoAmostra.objects.filter(cliente=cliente).aggregate(Max("coletado_em"))["coletado_em__max"]
        self.linha("\nEquipamentos (última coleta)")
        for e in EquipamentoAmostra.objects.filter(cliente=cliente, coletado_em=ultima).order_by("nome"):
            self.linha(f"  {e.nome or e.device_id}  {e.modelo}  {e.estado}  firmware {e.firmware or '—'}  "
                       f"CPU {num(e.cpu_pct, '{:.0f}%')}  memória {num(e.memoria_pct, '{:.0f}%')}")

        ultima = ClienteAmostra.objects.filter(cliente=cliente).aggregate(Max("coletado_em"))["coletado_em__max"]
        dispositivos = ClienteAmostra.objects.filter(cliente=cliente, coletado_em=ultima)
        wifi = dispositivos.filter(tipo="WIRELESS").count()
        self.linha(f"\nDispositivos conectados (última coleta): {dispositivos.count()} ({wifi} Wi-Fi, "
                   f"{dispositivos.count() - wifi} cabo)")

        nomes = Nomes()
        self.linha(f"\nAplicativos hoje ({hoje:%d/%m}, top 10 por download)")
        apps = (AplicativoDia.objects.filter(cliente=cliente, dia=hoje).values("categoria_id", "aplicativo_id")
                .annotate(d=Sum("download_bytes"), u=Sum("upload_bytes")).order_by("-d")[:10])
        for a in apps:
            nome = nomes.aplicativo(a["categoria_id"], a["aplicativo_id"])
            categoria = nomes.categoria(a["categoria_id"])
            self.linha(f"  {nome[:28]:<28} {categoria[:22]:<22} {gb(a['d'])}  {gb(a['u'])}")

        execucao = ExecucaoColeta.objects.filter(cliente=cliente).first()
        if execucao:
            self.linha(f"\nÚltima coleta: {timezone.localtime(execucao.iniciada_em, SP):%d/%m %H:%M} — "
                       f"{execucao.get_resultado_display()}")
            for p in execucao.partes:
                self.linha(f"  {'OK    ' if p['ok'] else 'FALHOU'} {p['nome']}: {p['mensagem']}")
