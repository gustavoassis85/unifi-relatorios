"""Atualiza as tabelas de tradução (1x por semana):
- categorias e aplicativos de DPI, pela API oficial do Network;
- sistemas operacionais, fabricantes, famílias e tipos de dispositivo, pela base de identificação
  do próprio console (fingerprint).
"""
from datetime import datetime, timezone

from banco.banco import conectar
from coletor.api import ErroApi
from coletor.consumo import deve_rodar, marcar
from coletor.equipamentos import CONSOLES_ATIVOS, Ritmo, _todos

INTERVALO_HORAS = 24 * 7
BLOCOS_FINGERPRINT = {  # bloco da resposta -> tipo no catálogo
    "os_name_ids": "so",
    "vendor_ids": "fabricante",
    "family_ids": "familia",
    "dev_type_ids": "tipo_dispositivo",
}


def _gravar(conexao, tipo, pares, agora):
    for id_, nome in pares:
        try:
            conexao.execute("INSERT OR REPLACE INTO catalogo VALUES (?, ?, ?, ?)", (tipo, int(id_), nome, agora))
        except (TypeError, ValueError):
            continue


def coletar():
    agora_dt = datetime.now(timezone.utc)
    agora = agora_dt.isoformat(timespec="seconds")
    conexao = conectar()
    try:
        vazio = conexao.execute("SELECT COUNT(*) FROM catalogo").fetchone()[0] == 0
        if not vazio and not deve_rodar(conexao, "catalogos", INTERVALO_HORAS, agora_dt):
            return "em dia (atualiza 1x por semana)"
        console = conexao.execute(CONSOLES_ATIVOS).fetchone()
        if not console:
            raise ErroApi("Nenhum console conectado no banco.")
        ritmo = Ritmo()
        base = f"/v1/connector/consoles/{console['host_id']}/network"
        with conexao:
            categorias = _todos(ritmo, f"{base}/integration/v1/dpi/categories")
            _gravar(conexao, "dpi_categoria", ((c.get("id"), c.get("name")) for c in categorias), agora)
            aplicativos = _todos(ritmo, f"{base}/integration/v1/dpi/applications")
            _gravar(conexao, "dpi_aplicativo", ((a.get("id"), a.get("name")) for a in aplicativos), agora)
            base_id = ritmo.get(f"{base}/v2/api/fingerprint_devices/0") or {}
            for bloco, tipo in BLOCOS_FINGERPRINT.items():
                valor = base_id.get(bloco)
                if isinstance(valor, dict):
                    _gravar(conexao, tipo, valor.items(), agora)
            marcar(conexao, "catalogos", agora_dt)
    finally:
        conexao.close()
    return f"{len(categorias)} categoria(s) e {len(aplicativos)} aplicativo(s) de DPI, base de identificação atualizada"
