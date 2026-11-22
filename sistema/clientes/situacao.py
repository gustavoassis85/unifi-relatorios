"""Situação de cada cliente para o painel lateral e os quadros da tela de clientes.

Tudo em poucas consultas, para todos os clientes da organização atual de uma vez (RLS e a
camada de isolamento filtram). Nada aqui grava no banco.

Situação (a cor do ponto):
- ok: a última coleta terminada deu certo e foi há menos de 2 h;
- atencao: a última coleta teve parte com erro, ou a última foi há mais de 2 h;
- falha: a última coleta falhou ou o último teste de conexão falhou;
- sem_coleta: sem chave da UniFi, sem console acompanhado ou nenhuma coleta ainda.
"""
from dataclasses import dataclass, field
from datetime import timedelta

from django.db.models import Count, Min, Q
from django.utils import timezone

HORAS = 24
ATRASO = timedelta(hours=2)
COM_PROBLEMA = ("atencao", "falha")
FILTROS = [("todos", "Todos"), ("problema", "Com problema"), ("sem_coleta", "Sem coleta")]


@dataclass
class Situacao:
    cliente: object
    estado: str = "sem_coleta"
    resumo: str = ""
    horas: list = field(default_factory=list)   # 24 itens, do mais antigo para a hora atual
    horas_ok: int = 0
    horas_com_coleta: int = 0
    ultimo_relatorio: object = None
    ultimo_envio: object = None
    proximo_agendamento: object = None

    @property
    def rotulo_estado(self):
        return {"ok": "Coletando", "atencao": "Atenção", "falha": "Com falha", "sem_coleta": "Sem coleta"}[self.estado]

    @property
    def descricao_horas(self):
        if not self.horas_com_coleta:
            return "Nenhuma coleta nas últimas 24 horas"
        return f"{self.horas_ok} de {HORAS} horas com coleta completa"


def _plural(n, singular, plural):
    return f"{n} {singular if n == 1 else plural}"


def situacao_dos_clientes(clientes, agora=None, completo=True):
    """[Situacao] na ordem de clientes. completo=False pula relatórios e agendamentos (painel lateral)."""
    from coletas.models import ExecucaoColeta, ResultadoExecucao
    from conexoes.models import ChaveUniFi, Console

    agora = agora or timezone.now()
    clientes = list(clientes)
    ids = [c.pk for c in clientes]
    if not ids:
        return []
    inicio = (agora - timedelta(hours=HORAS - 1)).replace(minute=0, second=0, microsecond=0)

    testes = dict(ChaveUniFi.objects.filter(cliente_id__in=ids).values_list("cliente_id", "teste_ok"))
    acompanhados = dict(Console.objects.filter(cliente_id__in=ids).values("cliente_id")
                        .annotate(n=Count("pk", filter=Q(acompanhar=True))).values_list("cliente_id", "n"))
    horas = {cid: [None] * HORAS for cid in ids}
    for cid, quando, resultado in (ExecucaoColeta.objects.filter(cliente_id__in=ids, iniciada_em__gte=inicio)
                                   .exclude(resultado=ResultadoExecucao.RODANDO)
                                   .order_by("iniciada_em").values_list("cliente_id", "iniciada_em", "resultado")):
        posicao = int((quando - inicio) / timedelta(hours=1))
        if 0 <= posicao < HORAS:
            horas[cid][posicao] = resultado   # a mais recente da hora fica
    ultimas = {}
    for cid, quando, resultado in (ExecucaoColeta.objects.filter(cliente_id__in=ids)
                                   .exclude(resultado=ResultadoExecucao.RODANDO)
                                   .order_by("cliente_id", "-iniciada_em").distinct("cliente_id")
                                   .values_list("cliente_id", "iniciada_em", "resultado")):
        ultimas[cid] = (quando, resultado)

    relatorios, envios, agendamentos = {}, {}, {}
    if completo:
        from envios.models import Agendamento, Envio
        from relatorios.models import Relatorio

        for r in (Relatorio.objects.filter(cliente_id__in=ids).defer("html", "pdf", "higiene")
                  .order_by("cliente_id", "-pedido_em").distinct("cliente_id")):
            relatorios[r.cliente_id] = r
        for e in (Envio.objects.filter(relatorio__in=list(relatorios.values()))
                  .order_by("relatorio_id", "-criado_em").distinct("relatorio_id")):
            envios[e.relatorio_id] = e
        agendamentos = dict(Agendamento.objects.filter(cliente_id__in=ids, ativo=True).values("cliente_id")
                            .annotate(p=Min("proxima_execucao")).values_list("cliente_id", "p"))

    saida = []
    for cliente in clientes:
        s = Situacao(cliente=cliente, horas=horas[cliente.pk])
        s.horas_ok = sum(1 for h in s.horas if h == "ok")
        s.horas_com_coleta = sum(1 for h in s.horas if h)
        n = acompanhados.get(cliente.pk, 0)
        ultima = ultimas.get(cliente.pk)
        if cliente.pk not in testes:
            s.estado, s.resumo = "sem_coleta", "Sem chave da UniFi"
        elif testes[cliente.pk] is False:
            s.estado, s.resumo = "falha", "O último teste de conexão falhou"
        elif n == 0:
            s.estado, s.resumo = "sem_coleta", "Nenhum console acompanhado"
        elif ultima is None:
            s.estado, s.resumo = "sem_coleta", "Ainda sem coleta"
        else:
            quando, resultado = ultima
            consoles = _plural(n, "console acompanhado", "consoles acompanhados")
            if resultado == "falhou":
                s.estado, s.resumo = "falha", "A última coleta falhou"
            elif agora - quando > ATRASO:
                horas_sem = int((agora - quando) / timedelta(hours=1))
                s.estado, s.resumo = "atencao", f"Sem coleta há {_plural(horas_sem, 'hora', 'horas')}"
            elif resultado == "parcial":
                s.estado, s.resumo = "atencao", f"{consoles}; parte da última coleta falhou"
            else:
                s.estado, s.resumo = "ok", consoles
        s.ultimo_relatorio = relatorios.get(cliente.pk)
        if s.ultimo_relatorio:
            s.ultimo_envio = envios.get(s.ultimo_relatorio.pk)
        s.proximo_agendamento = agendamentos.get(cliente.pk)
        saida.append(s)
    return saida


def filtrar(situacoes, filtro="todos", busca=""):
    busca = " ".join(busca.split()).lower()[:100]
    if busca:
        situacoes = [s for s in situacoes if busca in s.cliente.nome.lower()]
    if filtro == "problema":
        return [s for s in situacoes if s.estado in COM_PROBLEMA]
    if filtro == "sem_coleta":
        return [s for s in situacoes if s.estado == "sem_coleta"]
    return situacoes
