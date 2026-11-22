"""Tabelas de tradução, 1x por semana para a plataforma inteira (portado de coletor/catalogos.py):
categorias e aplicativos de DPI (API oficial) e sistemas, fabricantes, famílias e tipos de
dispositivo (base de identificação do console)."""
from datetime import timedelta

from django.db import transaction
from django.db.models import Max

from ..models import Catalogo
from ..tarefas import parte
from .apoio import texto
from .equipamentos import Ritmo, consoles_para_equipamentos, todos

INTERVALO = timedelta(days=7)
BLOCOS_IDENTIFICACAO = {"os_name_ids": "so", "vendor_ids": "fabricante", "family_ids": "familia",
                        "dev_type_ids": "tipo_dispositivo"}


def _linhas(tipo, pares, agora):
    linhas = []
    for id_, nome in pares:
        try:
            linhas.append(Catalogo(tipo=tipo, id_unifi=int(id_), nome=texto(nome, 200), atualizado_em=agora))
        except (TypeError, ValueError):
            continue
    return linhas


@parte("Catálogos", ordem=60)
def coletar(ctx):
    ultima = Catalogo.objects.aggregate(Max("atualizado_em"))["atualizado_em__max"]
    if ultima and ctx.agora - ultima < INTERVALO and not ctx.forcar:
        return "em dia (atualiza 1x por semana)"
    consoles = consoles_para_equipamentos(ctx)
    if not consoles:
        return "nenhum console conectado"
    ritmo = Ritmo(ctx.api)
    base = f"/v1/connector/consoles/{consoles[0].host_id}/network"
    categorias = todos(ritmo, f"{base}/integration/v1/dpi/categories")
    aplicativos = todos(ritmo, f"{base}/integration/v1/dpi/applications")
    identificacao = ritmo.get(f"{base}/v2/api/fingerprint_devices/0") or {}
    linhas = _linhas("dpi_categoria", ((c.get("id"), c.get("name")) for c in categorias), ctx.agora)
    linhas += _linhas("dpi_aplicativo", ((a.get("id"), a.get("name")) for a in aplicativos), ctx.agora)
    for bloco, tipo in BLOCOS_IDENTIFICACAO.items():
        if isinstance(identificacao.get(bloco), dict):
            linhas += _linhas(tipo, identificacao[bloco].items(), ctx.agora)
    with transaction.atomic():
        Catalogo.objects.bulk_create(linhas, update_conflicts=True, unique_fields=["tipo", "id_unifi"],
                                     update_fields=["nome", "atualizado_em"])
    return f"{len(categorias)} categoria(s) e {len(aplicativos)} aplicativo(s) de DPI, base de identificação atualizada"
