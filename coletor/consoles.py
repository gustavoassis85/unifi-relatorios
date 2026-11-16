"""Coleta da situação dos consoles pela Site Manager: /v1/hosts.

Cada coleta grava uma "foto" de cada console: conectado ou não, versões,
atualização pendente, último backup e WANs. Com fotos de hora em hora,
dá para calcular a disponibilidade do console no mês.

LGPD: a API também devolve e-mail do dono, localização e permissões de usuários.
Nada disso é gravado.
"""
from datetime import datetime, timezone

from banco.banco import conectar
from coletor.api import get

MAX_PAGINAS = 100  # trava de segurança contra laço infinito na paginação

GRAVAR = """
INSERT OR REPLACE INTO console_estado (
    host_id, coletado_em, nome, modelo, tipo, conectado, estado, versao_os, firmware,
    versao_network, atualizacao_disponivel, ultimo_backup, mudou_estado_em, wans_conectadas
) VALUES (
    :host_id, :coletado_em, :nome, :modelo, :tipo, :conectado, :estado, :versao_os, :firmware,
    :versao_network, :atualizacao_disponivel, :ultimo_backup, :mudou_estado_em, :wans_conectadas
)
"""


def _todos_os_hosts():
    """Busca todos os consoles, seguindo a paginação (nextToken) da API."""
    hosts, parametros = [], {"pageSize": 100}
    for _ in range(MAX_PAGINAS):
        resposta = get("/v1/hosts", parametros)
        hosts.extend(resposta.get("data", []))
        proximo = resposta.get("nextToken")
        if not proximo:
            break
        parametros["nextToken"] = proximo
    return hosts


def _versao_do_app(estado, nome_app):
    for app in estado.get("controllers") or []:
        if isinstance(app, dict) and app.get("name") == nome_app:
            return app.get("version") or None
    return None


def _linha(host, coletado_em):
    estado = host.get("reportedState") or {}
    hardware = estado.get("hardware") or {}
    tipo = host.get("type")
    wans = [w for w in estado.get("wans") or [] if isinstance(w, dict)]

    if tipo == "network-server":
        # Controlador Network instalado em servidor: a "versão" é a do Network, não há UniFi OS.
        versao_os, versao_network = None, estado.get("version")
    else:
        versao_os, versao_network = estado.get("version"), _versao_do_app(estado, "network")

    return {
        "host_id": host.get("id"),
        "coletado_em": coletado_em,
        "nome": estado.get("name") or estado.get("hostname"),
        "modelo": hardware.get("name"),
        "tipo": tipo,
        "conectado": 1 if estado.get("state") == "connected" else 0,
        "estado": estado.get("state"),
        "versao_os": versao_os,
        "firmware": hardware.get("firmwareVersion"),
        "versao_network": versao_network,
        "atualizacao_disponivel": (estado.get("firmwareUpdate") or {}).get("latestAvailableVersion"),
        "ultimo_backup": host.get("latestBackupTime") or None,
        "mudou_estado_em": host.get("lastConnectionStateChange") or None,
        "wans_conectadas": sum(1 for w in wans if w.get("plugged")),
    }


def coletar():
    """Busca os consoles, grava a foto de cada um e devolve um resumo em texto."""
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    linhas = [_linha(h, agora) for h in _todos_os_hosts()]
    linhas = [l for l in linhas if l["host_id"]]

    conexao = conectar()
    try:
        with conexao:
            conexao.executemany(GRAVAR, linhas)
    finally:
        conexao.close()

    online = sum(l["conectado"] for l in linhas)
    return f"{len(linhas)} console(s) gravado(s), {online} conectado(s)"
