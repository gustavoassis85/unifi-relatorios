"""Situação dos consoles pela Site Manager: /v1/hosts (portado de coletor/consoles.py).

Grava uma foto de cada console acompanhado a cada coleta e atualiza a lista de consoles
do cliente (a mesma do "Testar conexão"). LGPD: e-mail do dono, localização e usuários
que a API devolve não são gravados.
"""
from conexoes.models import Console
from conexoes.servicos import sincronizar_consoles
from unifi.api import resumir_hosts

from ..models import ConsoleEstado
from ..tarefas import parte
from .apoio import data, inteiro, texto


def _versao_do_app(estado, nome_app):
    for app in estado.get("controllers") or []:
        if isinstance(app, dict) and app.get("name") == nome_app:
            return app.get("version") or ""
    return ""


def foto(host, ctx, console):
    estado = host.get("reportedState") or {}
    hardware = estado.get("hardware") or {}
    tipo = host.get("type") or ""
    wans = [w for w in estado.get("wans") or [] if isinstance(w, dict)]
    if tipo == "network-server":
        # Network instalado em servidor: a "versão" é a do Network; não há UniFi OS.
        versao_os, versao_network = "", estado.get("version")
    else:
        versao_os, versao_network = estado.get("version"), _versao_do_app(estado, "network")
    return ConsoleEstado(
        organizacao_id=ctx.organizacao_id,
        cliente=ctx.cliente,
        console=console,
        coletado_em=ctx.agora,
        nome=texto(estado.get("name") or estado.get("hostname"), 150),
        modelo=texto(hardware.get("name"), 100),
        tipo=texto(tipo, 50),
        conectado=estado.get("state") == "connected",
        estado=texto(estado.get("state"), 50),
        versao_os=texto(versao_os, 50),
        firmware=texto(hardware.get("firmwareVersion"), 50),
        versao_network=texto(versao_network, 50),
        atualizacao_disponivel=texto((estado.get("firmwareUpdate") or {}).get("latestAvailableVersion"), 50),
        ultimo_backup=data(host.get("latestBackupTime")),
        mudou_estado_em=data(host.get("lastConnectionStateChange")),
        wans_conectadas=sum(1 for w in wans if w.get("plugged")),
    )


@parte("Consoles", ordem=10)
def coletar(ctx):
    hosts = ctx.api.listar_hosts()
    with ctx.banco():
        sincronizar_consoles(ctx.cliente, resumir_hosts(hosts), ctx.agora)
        acompanhados = {c.host_id: c for c in Console.objects.filter(cliente=ctx.cliente, acompanhar=True)}
        fotos = [foto(h, ctx, acompanhados[h["id"]]) for h in hosts if h.get("id") in acompanhados]
        ConsoleEstado.objects.bulk_create(fotos)
        # As partes seguintes usam a lista atualizada (equipamentos só nos conectados).
        ctx.consoles = list(acompanhados.values())
        ctx.extras["conectados"] = [c for c in ctx.consoles if c.conectado and c.na_conta]

    sumidos = sum(1 for c in ctx.consoles if not c.na_conta)
    resumo = f"{len(fotos)} console(s) acompanhado(s), {len(ctx.extras['conectados'])} conectado(s)"
    if sumidos:
        resumo += f"; {sumidos} não aparece(m) mais na conta"
    return resumo
