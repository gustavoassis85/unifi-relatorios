"""Pontos de atenção do relatório (portado de achados/regras.py do MVP).

Mesmas regras e mesmos LIMITES do MVP; muda só a origem dos dados (relatorios.fonte.Fonte).
Duas novidades em relação ao MVP:
- Incidentes: no mesmo console, "link sem dados" e "perda de pacote" que caem nos mesmos dias
  viram um ponto só, com as evidências juntas.
- Higiene da conta: achados da área "Conta" (registros antigos, consoles fora do acompanhamento)
  saem do relatório do cliente e ficam numa lista à parte, que só o MSP vê.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from statistics import mean, median
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Sao_Paulo")

LIMITES = {
    # Link (WAN)
    "wan_horas_sem_dado_alta": 8,       # total de horas sem dado no período para severidade alta
    "wan_sequencia_sem_dado_alta": 4,   # ou uma única sequência com pelo menos tantas horas
    "perda_dia_instavel": 1.5,          # % de perda média no dia para considerar o dia instável
    "perda_min_horas_dia": 12,          # dia com menos horas de dado não entra na conta de episódio
    "perda_dia_alta": 5.0,              # % de perda média num dia que torna o episódio grave
    "perda_hora_alta": 20.0,            # % de perda numa única hora que torna o episódio grave
    "perda_hora_pico": 10.0,            # % numa hora para registrar picos isolados
    "latencia_media": 50.0,             # ms (média do período)
    "latencia_media_alta": 100.0,       # ms
    # Consoles
    "console_offline_dias": 1,
    "registro_antigo_dias": 90,         # controlador desconectado há tanto tempo = registro antigo
    "backup_dias": 7,
    "backup_dias_alta": 30,
    # Disponibilidade de consoles e equipamentos (pelas fotos de hora em hora)
    "disponibilidade_min_amostras": 24,
    "disponibilidade_pct": 99.0,
    "disponibilidade_pct_alta": 95.0,
    # Equipamentos
    "carga_min_amostras": 6,
    "memoria_pct": 90.0,
    "cpu_pct": 80.0,
    "porta_dias": 7,                    # avalia as portas nos últimos N dias do período
    "porta_min_amostras": 3,
    "porta_fracao_abaixo": 0.8,         # fração das amostras com a porta abaixo da capacidade
    "retransmissao_min_amostras": 6,
    "retransmissao_pct": 10.0,
    # Clientes
    "wifi_min_amostras": 6,
    "sinal_fraco_dbm": -72,
    "sinal_muito_fraco_dbm": -80,
    "experiencia_minima": 70,
    "upload_dispositivo_bytes": 1e9,
    "upload_dispositivo_fracao": 0.5,
}

ORDEM_SEVERIDADE = {"alta": 0, "media": 1, "baixa": 2, "info": 3}
AREAS = ("Internet", "Console", "Equipamentos", "Wi-Fi", "Conta")


@dataclass
class Achado:
    host_id: str
    area: str           # Internet, Console, Equipamentos, Wi-Fi ou Conta
    severidade: str     # alta, media, baixa ou info
    titulo: str
    evidencia: str
    recomendacao: str = ""
    dias: set = field(default_factory=set)   # dias envolvidos (usado para juntar incidentes)
    tipo: str = ""                           # identifica a regra (usado para juntar incidentes)


# ---------------------------------------------------------------- utilidades

def _dt(momento):
    return momento.astimezone(FUSO)


def _num(valor, casas=1):
    return f"{valor:.{casas}f}".replace(".", ",")


def _dia(data):
    return data.strftime("%d/%m")


def _hora(momento):
    return momento.strftime("%d/%m %Hh")


def _qtd(n, singular, plural):
    return f"{n} {singular if n == 1 else plural}"


def _bytes(valor):
    valor = valor or 0
    if valor >= 1e9:
        return f"{_num(valor / 1e9)} GB"
    return f"{_num(valor / 1e6, 0)} MB"


def _intervalo(inicio, horas):
    fim = inicio + timedelta(hours=horas)
    if horas == 1:
        return f"{_hora(inicio)} (1h)"
    if fim.date() == inicio.date():
        return f"{inicio:%d/%m} das {inicio:%H}h às {fim:%H}h ({horas}h)"
    return f"de {_hora(inicio)} a {_hora(fim)} ({horas}h)"


def _agrupar_horas(horas):
    grupos = []
    for hora in sorted(horas):
        if grupos and hora - grupos[-1][0] == timedelta(hours=grupos[-1][1]):
            grupos[-1][1] += 1
        else:
            grupos.append([hora, 1])
    return [(inicio, n) for inicio, n in grupos]


# ---------------------------------------------------------------- link (WAN)

def regra_wan_sem_dado(fonte, inicio, fim):
    achados = []
    for (host_id, _site), horas in fonte.wan_por_site(inicio, fim).items():
        presentes = {_dt(h["horario"]) for h in horas}
        atual, ultima, faltando = min(presentes), max(presentes), []
        while atual <= ultima:
            if atual not in presentes:
                faltando.append(atual)
            atual += timedelta(hours=1)
        if not faltando:
            continue
        sequencias = _agrupar_horas(faltando)
        maior = max(n for _, n in sequencias)
        grave = (len(faltando) >= LIMITES["wan_horas_sem_dado_alta"]
                 or maior >= LIMITES["wan_sequencia_sem_dado_alta"])
        partes = [_intervalo(ini, n) for ini, n in sequencias[:5]]
        if len(sequencias) > 5:
            partes.append(f"mais {_qtd(len(sequencias) - 5, 'intervalo', 'intervalos')}")
        achados.append(Achado(
            host_id, "Internet", "alta" if grave else "media",
            f"Link sem dados por {_qtd(len(faltando), 'hora', 'horas')}",
            f"{_qtd(len(faltando), 'hora', 'horas')} sem nenhuma métrica do link: {'; '.join(partes)}. "
            "Hora sem registro costuma indicar queda da internet ou do console.",
            dias={h.date() for h in faltando}, tipo="wan_sem_dado",
        ))
    return achados


def regra_wan_perda(fonte, inicio, fim):
    achados = []
    for (host_id, _site), horas in fonte.wan_por_site(inicio, fim).items():
        horas = [h for h in horas if h["perda_pct"] is not None]
        if not horas:
            continue
        provedor = next((h["provedor"] for h in horas if h["provedor"]), "operadora")
        por_dia = defaultdict(list)
        for h in horas:
            por_dia[_dt(h["horario"]).date()].append(h)
        medias = {dia: mean(h["perda_pct"] for h in hs) for dia, hs in por_dia.items()
                  if len(hs) >= LIMITES["perda_min_horas_dia"]}

        episodios = []
        for dia in sorted(medias):
            if medias[dia] >= LIMITES["perda_dia_instavel"]:
                if episodios and (dia - episodios[-1][-1]).days == 1:
                    episodios[-1].append(dia)
                else:
                    episodios.append([dia])

        if episodios:
            dias_instaveis = {d for ep in episodios for d in ep}
            normais = [m for d, m in medias.items() if d not in dias_instaveis]
            textos, grave = [], False
            for ep in episodios:
                pico = max((h for d in ep for h in por_dia[d]), key=lambda h: h["perda_pct"])
                maior_media = max(medias[d] for d in ep)
                grave = grave or maior_media >= LIMITES["perda_dia_alta"] \
                    or pico["perda_pct"] >= LIMITES["perda_hora_alta"]
                quando = _dia(ep[0]) if len(ep) == 1 else f"{_dia(ep[0])} a {_dia(ep[-1])}"
                textos.append(
                    f"{quando} (média diária de até {_num(maior_media)}%, "
                    f"pico de {_num(pico['perda_pct'], 0)}% em {_hora(_dt(pico['horario']))})"
                )
            evidencia = f"{_qtd(len(episodios), 'período', 'períodos')} de instabilidade: {'; '.join(textos)}."
            if normais:
                fora = "Fora desse período" if len(episodios) == 1 else "Fora desses períodos"
                evidencia += f" {fora}, a perda média diária ficou em torno de {_num(median(normais))}%."
            achados.append(Achado(
                host_id, "Internet", "alta" if grave else "media",
                f"Perda de pacote acima do normal no link {provedor}", evidencia,
                dias=dias_instaveis, tipo="wan_perda",
            ))
            continue

        picos = [h for h in horas if h["perda_pct"] >= LIMITES["perda_hora_pico"]]
        if picos:
            maior = max(picos, key=lambda h: h["perda_pct"])
            achados.append(Achado(
                host_id, "Internet", "baixa", f"Picos isolados de perda de pacote no link {provedor}",
                f"{_qtd(len(picos), 'hora', 'horas')} com perda acima de {_num(LIMITES['perda_hora_pico'], 0)}%, "
                f"a maior de {_num(maior['perda_pct'], 0)}% em {_hora(_dt(maior['horario']))}. "
                "A média diária ficou normal.",
                dias={_dt(h["horario"]).date() for h in picos}, tipo="wan_picos",
            ))
    return achados


def regra_wan_latencia(fonte, inicio, fim):
    achados = []
    for (host_id, _site), horas in fonte.wan_por_site(inicio, fim).items():
        valores = [h["latencia_media"] for h in horas if h["latencia_media"] is not None]
        if not valores or mean(valores) < LIMITES["latencia_media"]:
            continue
        media = mean(valores)
        provedor = next((h["provedor"] for h in horas if h["provedor"]), "operadora")
        achados.append(Achado(
            host_id, "Internet", "alta" if media >= LIMITES["latencia_media_alta"] else "media",
            f"Latência alta no link {provedor}",
            f"Latência média de {_num(media)} ms no período (máxima registrada de "
            f"{_num(max(h['latencia_max'] or 0 for h in horas), 0)} ms).",
            tipo="wan_latencia",
        ))
    return achados


# ---------------------------------------------------------------- consoles

def regra_console_offline(fonte, inicio, fim):
    achados = []
    for c in fonte.ultimos_consoles():
        if c["conectado"]:
            continue
        desde = _dt(c["mudou_estado_em"]) if c["mudou_estado_em"] else None
        dias = (_dt(fim) - desde).days if desde else None
        quando = f"desde {desde.strftime('%d/%m/%Y')} ({dias} dias)" if desde else "sem data registrada"
        if c["tipo"] == "network-server":
            if dias is None or dias >= LIMITES["registro_antigo_dias"]:
                achados.append(Achado(
                    c["host_id"], "Conta", "info", "Registro antigo de controlador na conta",
                    f"Controlador Network {c['versao_network'] or ''} desconectado {quando}.".replace("  ", " "),
                    tipo="registro_antigo",
                ))
        elif dias is None or dias >= LIMITES["console_offline_dias"]:
            achados.append(Achado(
                c["host_id"], "Console", "alta", "Console sem conexão com a nuvem",
                f"{c['nome']} ({c['modelo'] or 'console'}) está desconectado {quando}. "
                "Sem conexão, não há monitoramento, alertas nem backup em nuvem.",
                tipo="console_offline",
            ))
    return achados


def regra_console_disponibilidade(fonte, inicio, fim):
    achados = []
    fotos = defaultdict(list)
    for f in fonte.fotos_consoles(inicio, fim):
        if f["tipo"] == "console":
            fotos[f["host_id"]].append(f["conectado"])
    atuais = {c["host_id"]: c for c in fonte.ultimos_consoles()}
    for host_id, estados in fotos.items():
        if len(estados) < LIMITES["disponibilidade_min_amostras"] or not atuais[host_id]["conectado"]:
            continue
        pct = 100 * sum(estados) / len(estados)
        if pct >= LIMITES["disponibilidade_pct"]:
            continue
        achados.append(Achado(
            host_id, "Console", "alta" if pct < LIMITES["disponibilidade_pct_alta"] else "media",
            "Console com quedas de conexão no período",
            f"Conectado em {_num(pct)}% das {len(estados)} verificações de hora em hora.",
            tipo="console_disponibilidade",
        ))
    return achados


def regra_backup(fonte, inicio, fim):
    achados = []
    for c in fonte.ultimos_consoles():
        if not c["conectado"] or c["tipo"] != "console":
            continue
        if not c["ultimo_backup"]:
            achados.append(Achado(
                c["host_id"], "Console", "alta", "Console sem backup em nuvem",
                f"Não há registro de backup em nuvem para {c['nome']}.", tipo="backup",
            ))
            continue
        backup = _dt(c["ultimo_backup"])
        dias = (_dt(fim) - backup).days
        if dias < LIMITES["backup_dias"]:
            continue
        achados.append(Achado(
            c["host_id"], "Console", "alta" if dias >= LIMITES["backup_dias_alta"] else "media",
            "Backup em nuvem desatualizado",
            f"Último backup em nuvem de {c['nome']} em {backup.strftime('%d/%m/%Y')} ({dias} dias).",
            tipo="backup",
        ))
    return achados


def regra_atualizacao_console(fonte, inicio, fim):
    achados = []
    for c in fonte.ultimos_consoles():
        if not c["conectado"] or not c["atualizacao_disponivel"]:
            continue
        primeira = fonte.primeira_vez_com_atualizacao(c["host_id"], c["atualizacao_disponivel"])
        nova = c["atualizacao_disponivel"].split("+")[0]
        achados.append(Achado(
            c["host_id"], "Console", "media", "Atualização do sistema do console pendente",
            f"{c['nome']} está na versão {c['firmware'] or c['versao_os']}; a versão {nova} está disponível "
            f"(detectada em {_dt(primeira).strftime('%d/%m/%Y')}).",
            tipo="atualizacao_console",
        ))
    return achados


# ---------------------------------------------------------------- equipamentos

def regra_equipamentos(fonte, inicio, fim):
    achados = []
    amostras = defaultdict(list)
    for a in fonte.equipamento_amostras(inicio, fim):
        amostras[a["device_id"]].append(a)

    for lista in amostras.values():
        ultima = lista[-1]
        host_id, nome = ultima["host_id"], f"{ultima['nome']} ({ultima['modelo']})"

        if len(lista) >= LIMITES["disponibilidade_min_amostras"]:
            pct = 100 * sum(1 for a in lista if a["estado"] == "ONLINE") / len(lista)
            if pct < LIMITES["disponibilidade_pct"]:
                achados.append(Achado(
                    host_id, "Equipamentos", "alta" if pct < LIMITES["disponibilidade_pct_alta"] else "media",
                    f"{nome} ficou offline no período",
                    f"Online em {_num(pct)}% das {len(lista)} verificações.", tipo="equipamento_offline",
                ))

        reinicios = []
        for anterior, atual in zip(lista, lista[1:]):
            if anterior["uptime_seg"] is not None and atual["uptime_seg"] is not None \
                    and atual["uptime_seg"] < anterior["uptime_seg"]:
                reinicios.append(_dt(atual["coletado_em"]) - timedelta(seconds=atual["uptime_seg"]))
        if reinicios:
            achados.append(Achado(
                host_id, "Equipamentos", "baixa", f"{nome} reiniciou {_qtd(len(reinicios), 'vez', 'vezes')}",
                ("Reinício" if len(reinicios) == 1 else "Reinícios") + " por volta de "
                + ", ".join(_hora(r) for r in reinicios) + ".",
                tipo="reinicio",
            ))

        com_carga = [a for a in lista if a["cpu_pct"] is not None]
        if len(com_carga) >= LIMITES["carga_min_amostras"]:
            memorias = [a["memoria_pct"] for a in com_carga if a["memoria_pct"] is not None]
            memoria = mean(memorias) if memorias else 0
            cpu = mean(a["cpu_pct"] for a in com_carga)
            if memoria >= LIMITES["memoria_pct"]:
                achados.append(Achado(
                    host_id, "Equipamentos", "media", f"Memória alta em {nome}",
                    f"Uso médio de memória de {_num(memoria)}% em {len(com_carga)} amostras.", tipo="memoria",
                ))
            if cpu >= LIMITES["cpu_pct"]:
                achados.append(Achado(
                    host_id, "Equipamentos", "media", f"CPU alta em {nome}",
                    f"Uso médio de CPU de {_num(cpu)}% em {len(com_carga)} amostras.", tipo="cpu",
                ))

        if ultima["firmware_atualizavel"]:
            achados.append(Achado(
                host_id, "Equipamentos", "media", f"Firmware desatualizado em {nome}",
                f"{nome} está no firmware {ultima['firmware']} e há atualização disponível.", tipo="firmware",
            ))
    return achados


def regra_portas(fonte, inicio, fim):
    """Porta ativa negociando abaixo da capacidade, de forma persistente (várias amostras)."""
    achados = []
    janela = max(inicio, fim - timedelta(days=LIMITES["porta_dias"]))
    equipamentos = fonte.ultimos_equipamentos()
    portas = defaultdict(list)
    for p in fonte.portas_ativas(janela, fim):
        portas[(p["device_id"], p["idx"])].append(p)

    for (device_id, idx), lista in sorted(portas.items()):
        if len(lista) < LIMITES["porta_min_amostras"] or device_id not in equipamentos:
            continue
        abaixo = [p for p in lista if (p["velocidade_mbps"] or 0) < (p["velocidade_max_mbps"] or 0)]
        if len(abaixo) / len(lista) < LIMITES["porta_fracao_abaixo"]:
            continue
        e = equipamentos[device_id]
        achados.append(Achado(
            e["host_id"], "Equipamentos", "media", f"Porta {idx} de {e['nome']} abaixo da capacidade",
            f"Negociando a {abaixo[-1]['velocidade_mbps']} Mbps (capacidade de "
            f"{abaixo[-1]['velocidade_max_mbps']} Mbps) em {len(abaixo)} de {len(lista)} verificações.",
            tipo="porta",
        ))
    return achados


def regra_radios(fonte, inicio, fim):
    achados = []
    equipamentos = fonte.ultimos_equipamentos()

    retransmissao = defaultdict(list)
    for r in fonte.radio_amostras(inicio, fim):
        if r["retransmissao_pct"] is not None:
            retransmissao[(r["device_id"], r["posicao"], r["frequencia_ghz"])].append(r["retransmissao_pct"])
    for (device_id, _pos, freq), valores in retransmissao.items():
        if len(valores) < LIMITES["retransmissao_min_amostras"] or device_id not in equipamentos:
            continue
        if mean(valores) >= LIMITES["retransmissao_pct"]:
            e = equipamentos[device_id]
            achados.append(Achado(
                e["host_id"], "Wi-Fi", "media", f"Wi-Fi {freq or 0:g} GHz com muita retransmissão em {e['nome']}",
                f"Retransmissão média de {_num(mean(valores))}% em {len(valores)} amostras.", tipo="retransmissao",
            ))

    for device_id, e in equipamentos.items():
        for r in fonte.radios_configurados(device_id):
            freq = f"{r['frequencia_ghz'] or 0:g} GHz"
            if not r["canal"]:
                achados.append(Achado(
                    e["host_id"], "Wi-Fi", "info", f"Rádio {freq} de {e['nome']} sem canal ativo",
                    f"O rádio {freq} não informa canal; provavelmente está desligado.", tipo="radio_sem_canal",
                ))
            elif r["frequencia_ghz"] and r["frequencia_ghz"] < 3 and (r["largura_mhz"] or 0) > 20:
                achados.append(Achado(
                    e["host_id"], "Wi-Fi", "media", f"Canal largo demais no 2.4 GHz de {e['nome']}",
                    f"Rádio 2.4 GHz configurado com {r['largura_mhz']} MHz.", tipo="canal_largo",
                ))
    return achados


# ---------------------------------------------------------------- dispositivos

def regra_wifi_clientes(fonte, inicio, fim):
    achados = []
    amostras = defaultdict(list)
    for c in fonte.amostras_wifi(inicio, fim):
        amostras[(c["host_id"], c["mac"])].append(c)

    fracos, ruins = defaultdict(list), defaultdict(list)
    for (host_id, _mac), lista in amostras.items():
        if len(lista) < LIMITES["wifi_min_amostras"]:
            continue
        nome, ssid = lista[-1]["nome"] or lista[-1]["mac"], lista[-1]["ssid"]
        sinais = [c["sinal_dbm"] for c in lista if c["sinal_dbm"] is not None]
        notas = [c["experiencia"] for c in lista if c["experiencia"] is not None]
        if sinais and mean(sinais) <= LIMITES["sinal_fraco_dbm"]:
            fracos[host_id].append((mean(sinais), nome, ssid))
        elif notas and mean(notas) < LIMITES["experiencia_minima"]:
            ruins[host_id].append((mean(notas), nome, ssid))

    for host_id, lista in fracos.items():
        lista.sort()
        grave = lista[0][0] <= LIMITES["sinal_muito_fraco_dbm"] or len(lista) >= 3
        itens = "; ".join(f"{nome} ({_num(sinal, 0)} dBm, rede {ssid})" for sinal, nome, ssid in lista[:5])
        achados.append(Achado(
            host_id, "Wi-Fi", "media" if grave else "baixa",
            f"{_qtd(len(lista), 'dispositivo', 'dispositivos')} com sinal Wi-Fi fraco",
            f"Sinal médio no período: {itens}. Sinal fraco causa lentidão e quedas.", tipo="sinal_fraco",
        ))
    for host_id, lista in ruins.items():
        lista.sort()
        itens = "; ".join(f"{nome} (nota {_num(nota, 0)}, rede {ssid})" for nota, nome, ssid in lista[:5])
        achados.append(Achado(
            host_id, "Wi-Fi", "media", f"{_qtd(len(lista), 'dispositivo', 'dispositivos')} com experiência Wi-Fi ruim",
            f"Nota média de experiência do UniFi no período: {itens}.", tipo="experiencia_ruim",
        ))
    return achados


def regra_upload_dispositivo(fonte, inicio, fim):
    achados = []
    dia_ini, dia_fim = _dt(inicio).date(), _dt(fim).date()
    for s in fonte.upload_por_site(dia_ini, dia_fim):
        if not s["upload"]:
            continue
        topo = fonte.maior_upload(s["host_id"], s["site"], dia_ini, dia_fim)
        if not topo or not topo["upload"]:
            continue
        fracao = topo["upload"] / s["upload"]
        if topo["upload"] < LIMITES["upload_dispositivo_bytes"] or fracao < LIMITES["upload_dispositivo_fracao"] \
                or topo["upload"] <= (topo["download"] or 0):
            continue
        nome = fonte.nome_dispositivo(s["host_id"], topo["mac"])
        if fracao <= 1:
            comparacao = f"o equivalente a {_num(100 * fracao, 0)}% de todo o upload da internet do site"
        else:
            comparacao = "mais que todo o upload da internet do site (parte é tráfego na rede local)"
        achados.append(Achado(
            s["host_id"], "Internet", "info", f"{nome} concentra o upload da rede",
            f"{nome} enviou {_bytes(topo['upload'])} no período, {comparacao} "
            f"({_bytes(s['upload'])}), e enviou mais do que recebeu.", tipo="upload_dispositivo",
        ))
    return achados


# ---------------------------------------------------------------- incidentes e higiene

def juntar_incidentes(achados):
    """No mesmo console, "link sem dados" e "perda de pacote" com dias em comum viram um ponto só."""
    sem_dado = {a.host_id: a for a in achados if a.tipo == "wan_sem_dado"}
    resultado = []
    usados = set()
    for a in achados:
        par = sem_dado.get(a.host_id) if a.tipo == "wan_perda" else None
        if par is None or not (a.dias & par.dias):
            continue
        provedor = a.titulo.rsplit("no link ", 1)[-1]
        resultado.append(Achado(
            a.host_id, "Internet", min(a.severidade, par.severidade, key=ORDEM_SEVERIDADE.get),
            f"Quedas e perda de pacote no link {provedor}",
            f"{par.evidencia} {a.evidencia}", dias=a.dias | par.dias, tipo="incidente_link",
        ))
        usados.update({id(a), id(par)})
    return resultado + [a for a in achados if id(a) not in usados]


def regra_higiene_consoles(consoles_da_conta):
    """Consoles da conta do cliente que estão desconectados e fora do acompanhamento."""
    achados = []
    for c in consoles_da_conta:
        if c.acompanhar or c.conectado:
            continue
        situacao = "não aparece mais na conta" if not c.na_conta else "desconectado"
        achados.append(Achado(
            c.host_id, "Conta", "info", f"{c.nome or c.host_id} fora do acompanhamento",
            f"{c.nome or c.host_id} ({c.modelo or c.tipo or 'console'}) está {situacao} e não é acompanhado. "
            "Se não existe mais, remover o registro da conta UniFi.", tipo="higiene_console",
        ))
    return achados


REGRAS = [
    regra_wan_sem_dado, regra_wan_perda, regra_wan_latencia,
    regra_console_offline, regra_console_disponibilidade, regra_backup, regra_atualizacao_console,
    regra_equipamentos, regra_portas, regra_radios,
    regra_wifi_clientes, regra_upload_dispositivo,
]


def _ordenar(achados):
    return sorted(achados, key=lambda a: (ORDEM_SEVERIDADE[a.severidade], AREAS.index(a.area)))


def avaliar(fonte, inicio, fim, consoles_da_conta=()):
    """Roda as regras no período. Devolve (achados do relatório, higiene da conta, erros)."""
    achados, erros = [], []
    for regra in REGRAS:
        try:
            achados.extend(regra(fonte, inicio, fim))
        except Exception as erro:  # noqa: BLE001 - uma regra com problema não derruba as outras
            erros.append(f"{regra.__name__}: {erro.__class__.__name__}")
    achados = juntar_incidentes(achados)
    achados.extend(regra_higiene_consoles(consoles_da_conta))
    higiene = [a for a in achados if a.area == "Conta"]
    relatorio = [a for a in achados if a.area != "Conta"]
    return _ordenar(relatorio), _ordenar(higiene), erros
