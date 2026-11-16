"""Motor de achados: transforma os dados coletados em pontos de atenção com severidade,
evidência e recomendação, separados pela área afetada (internet, console, equipamentos, Wi-Fi).

- Os limites de cada regra ficam em LIMITES, logo abaixo, para facilitar ajustes.
- Cada regra exige um mínimo de amostras, para não tirar conclusão com pouco dado.
- Se uma regra der erro, as outras continuam (o erro é devolvido à parte).
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import mean, median

# Horário de Brasília. O Brasil não tem horário de verão desde 2019, então o fuso é fixo.
FUSO = timezone(timedelta(hours=-3))

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
    "memoria_pct": 90.0,                # média do período
    "cpu_pct": 80.0,                    # média do período
    "porta_dias": 7,                    # avalia as portas nos últimos N dias do período
    "porta_min_amostras": 3,
    "porta_fracao_abaixo": 0.8,         # fração das amostras com a porta abaixo da capacidade
    "retransmissao_min_amostras": 6,
    "retransmissao_pct": 10.0,          # média do período por rádio
}

ORDEM_SEVERIDADE = {"alta": 0, "media": 1, "baixa": 2, "info": 3}
AREAS = ("Internet", "Console", "Equipamentos", "Wi-Fi", "Conta")


@dataclass
class Achado:
    host_id: str        # console ao qual o achado pertence
    area: str           # Internet, Console, Equipamentos, Wi-Fi ou Conta
    severidade: str     # alta, media, baixa ou info
    titulo: str
    evidencia: str
    recomendacao: str


# ---------------------------------------------------------------- utilidades

def _dt(texto):
    """Data da API ou do banco (UTC) convertida para o horário de Brasília."""
    return datetime.fromisoformat(texto.replace("Z", "+00:00")).astimezone(FUSO)


def _chave(momento):
    """Momento no formato usado para comparar com as datas gravadas no banco."""
    return momento.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _num(valor, casas=1):
    return f"{valor:.{casas}f}".replace(".", ",")


def _dia(data):
    return data.strftime("%d/%m")


def _hora(momento):
    return momento.strftime("%d/%m %Hh")


def _qtd(n, singular, plural):
    """Ex.: _qtd(1, "hora", "horas") -> "1 hora"; _qtd(17, ...) -> "17 horas"."""
    return f"{n} {singular if n == 1 else plural}"


def _no_periodo(conexao, sql, inicio, fim, coluna="coletado_em"):
    """Executa um SELECT filtrando a coluna de data pelo período."""
    filtro = f" WHERE substr({coluna}, 1, 19) >= ? AND substr({coluna}, 1, 19) <= ?"
    return conexao.execute(sql + filtro + f" ORDER BY {coluna}", (_chave(inicio), _chave(fim))).fetchall()


def _ultimos_consoles(conexao):
    return conexao.execute(
        "SELECT * FROM console_estado c WHERE coletado_em = "
        "(SELECT MAX(coletado_em) FROM console_estado WHERE host_id = c.host_id)"
    ).fetchall()


def _ultimos_equipamentos(conexao):
    """Último registro de cada equipamento: console, nome e modelo."""
    linhas = conexao.execute(
        "SELECT * FROM equipamento_amostra e WHERE coletado_em = "
        "(SELECT MAX(coletado_em) FROM equipamento_amostra WHERE device_id = e.device_id)"
    ).fetchall()
    return {e["device_id"]: e for e in linhas}


def _wan_por_site(conexao, inicio, fim):
    sites = defaultdict(list)
    for linha in _no_periodo(conexao, "SELECT * FROM wan_hora", inicio, fim, "horario"):
        sites[(linha["host_id"], linha["site_id"])].append(linha)
    return sites


def _intervalo(inicio, horas):
    """Texto de um intervalo de horas: '26/10 16h (1h)', '26/10 das 08h às 12h (4h)' ou
    'de 26/10 18h a 27/10 07h (13h)'."""
    fim = inicio + timedelta(hours=horas)
    if horas == 1:
        return f"{_hora(inicio)} (1h)"
    if fim.date() == inicio.date():
        return f"{inicio:%d/%m} das {inicio:%H}h às {fim:%H}h ({horas}h)"
    return f"de {_hora(inicio)} a {_hora(fim)} ({horas}h)"


def _agrupar_horas(horas):
    """Agrupa horas consecutivas: [(início, quantidade de horas), ...]."""
    grupos = []
    for hora in sorted(horas):
        if grupos and hora - grupos[-1][0] == timedelta(hours=grupos[-1][1]):
            grupos[-1][1] += 1
        else:
            grupos.append([hora, 1])
    return [(inicio, n) for inicio, n in grupos]


# ---------------------------------------------------------------- regras do link (WAN)

def regra_wan_sem_dado(conexao, inicio, fim):
    achados = []
    for (host_id, _site), horas in _wan_por_site(conexao, inicio, fim).items():
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
            "Confirmar com o provedor se houve interrupção nesses horários e pedir o protocolo. "
            "Se as quedas se repetirem, avaliar um segundo link com failover.",
        ))
    return achados


def regra_wan_perda(conexao, inicio, fim):
    achados = []
    for (host_id, _site), horas in _wan_por_site(conexao, inicio, fim).items():
        horas = [h for h in horas if h["perda_pct"] is not None]
        if not horas:
            continue
        provedor = next((h["provedor"] for h in horas if h["provedor"]), "operadora")
        por_dia = defaultdict(list)
        for h in horas:
            por_dia[_dt(h["horario"]).date()].append(h)
        medias = {dia: mean(h["perda_pct"] for h in hs) for dia, hs in por_dia.items()
                  if len(hs) >= LIMITES["perda_min_horas_dia"]}

        # Episódio = dias seguidos com perda média acima do limite.
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
                f"Abrir chamado com a {provedor} informando as datas e horários. Verificar ONT/modem "
                "e o cabo da WAN. Se persistir, avaliar um link de redundância.",
            ))
            continue

        picos = [h for h in horas if h["perda_pct"] >= LIMITES["perda_hora_pico"]]
        if picos:
            maior = max(picos, key=lambda h: h["perda_pct"])
            achados.append(Achado(
                host_id, "Internet", "baixa", f"Picos isolados de perda de pacote no link {provedor}",
                f"{_qtd(len(picos), 'hora', 'horas')} com perda acima de {_num(LIMITES['perda_hora_pico'], 0)}%, a maior de "
                f"{_num(maior['perda_pct'], 0)}% em {_hora(_dt(maior['horario']))}. A média diária ficou normal.",
                "Acompanhar. Se os picos ficarem mais frequentes, acionar o provedor.",
            ))
    return achados


def regra_wan_latencia(conexao, inicio, fim):
    achados = []
    for (host_id, _site), horas in _wan_por_site(conexao, inicio, fim).items():
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
            "Verificar com o provedor a rota e a qualidade do link; latência alta afeta chamadas, "
            "videoconferências e sistemas em nuvem.",
        ))
    return achados


# ---------------------------------------------------------------- regras dos consoles

def regra_console_offline(conexao, inicio, fim):
    achados = []
    for c in _ultimos_consoles(conexao):
        if c["conectado"]:
            continue
        desde = _dt(c["mudou_estado_em"]) if c["mudou_estado_em"] else None
        dias = (fim.astimezone(FUSO) - desde).days if desde else None
        quando = f"desde {desde.strftime('%d/%m/%Y')} ({dias} dias)" if desde else "sem data registrada"

        if c["tipo"] == "network-server":
            if dias is None or dias >= LIMITES["registro_antigo_dias"]:
                achados.append(Achado(
                    c["host_id"], "Conta", "info", "Registro antigo de controlador na conta",
                    f"Controlador Network {c['versao_network'] or ''} desconectado {quando}.".replace("  ", " "),
                    "Se o controlador não existe mais, remover o registro da conta UniFi para manter o "
                    "inventário limpo.",
                ))
        elif dias is None or dias >= LIMITES["console_offline_dias"]:
            achados.append(Achado(
                c["host_id"], "Console", "alta", "Console sem conexão com a nuvem",
                f"{c['nome']} ({c['modelo'] or 'console'}) está desconectado {quando}. "
                "Sem conexão, não há monitoramento, alertas nem backup em nuvem.",
                "Verificar se o equipamento está ligado e com internet. Se foi desativado, "
                "removê-lo da conta.",
            ))
    return achados


def regra_console_disponibilidade(conexao, inicio, fim):
    achados = []
    fotos = defaultdict(list)
    for f in _no_periodo(conexao, "SELECT host_id, conectado, tipo FROM console_estado", inicio, fim):
        if f["tipo"] == "console":
            fotos[f["host_id"]].append(f["conectado"])
    atuais = {c["host_id"]: c for c in _ultimos_consoles(conexao)}
    for host_id, estados in fotos.items():
        if len(estados) < LIMITES["disponibilidade_min_amostras"] or not atuais[host_id]["conectado"]:
            continue  # pouco dado, ou o console já está offline (outra regra cobre)
        pct = 100 * sum(estados) / len(estados)
        if pct >= LIMITES["disponibilidade_pct"]:
            continue
        achados.append(Achado(
            host_id, "Console", "alta" if pct < LIMITES["disponibilidade_pct_alta"] else "media",
            "Console com quedas de conexão no período",
            f"Conectado em {_num(pct)}% das {len(estados)} verificações de hora em hora.",
            "Investigar a estabilidade da internet e da energia no local do console.",
        ))
    return achados


def regra_backup(conexao, inicio, fim):
    achados = []
    for c in _ultimos_consoles(conexao):
        if not c["conectado"] or c["tipo"] != "console":
            continue
        if not c["ultimo_backup"]:
            achados.append(Achado(
                c["host_id"], "Console", "alta", "Console sem backup em nuvem",
                f"Não há registro de backup em nuvem para {c['nome']}.",
                "Ativar o backup automático em nuvem no console e confirmar que ele está sendo gerado.",
            ))
            continue
        backup = _dt(c["ultimo_backup"])
        dias = (fim.astimezone(FUSO) - backup).days
        if dias < LIMITES["backup_dias"]:
            continue
        achados.append(Achado(
            c["host_id"], "Console", "alta" if dias >= LIMITES["backup_dias_alta"] else "media",
            "Backup em nuvem desatualizado",
            f"Último backup em nuvem de {c['nome']} em {backup.strftime('%d/%m/%Y')} ({dias} dias).",
            "Verificar se o backup automático está ativo e se está concluindo sem erro.",
        ))
    return achados


def regra_atualizacao_console(conexao, inicio, fim):
    achados = []
    for c in _ultimos_consoles(conexao):
        if not c["conectado"] or not c["atualizacao_disponivel"]:
            continue
        primeira = conexao.execute(
            "SELECT MIN(coletado_em) FROM console_estado WHERE host_id = ? AND atualizacao_disponivel = ?",
            (c["host_id"], c["atualizacao_disponivel"]),
        ).fetchone()[0]
        nova = c["atualizacao_disponivel"].split("+")[0]
        achados.append(Achado(
            c["host_id"], "Console", "media", "Atualização do sistema do console pendente",
            f"{c['nome']} está na versão {c['firmware'] or c['versao_os']}; a versão {nova} está disponível "
            f"(detectada em {_dt(primeira).strftime('%d/%m/%Y')}).",
            "Planejar a atualização numa janela de manutenção, depois de ler as notas da versão.",
        ))
    return achados


# ---------------------------------------------------------------- regras dos equipamentos

def regra_equipamentos(conexao, inicio, fim):
    """Disponibilidade, reinícios, carga e firmware de cada equipamento."""
    achados = []
    amostras = defaultdict(list)
    for a in _no_periodo(conexao, "SELECT * FROM equipamento_amostra", inicio, fim):
        amostras[a["device_id"]].append(a)

    for lista in amostras.values():
        ultima = lista[-1]
        host_id, nome = ultima["host_id"], f"{ultima['nome']} ({ultima['modelo']})"

        if len(lista) >= LIMITES["disponibilidade_min_amostras"]:
            pct = 100 * sum(1 for a in lista if a["estado"] == "ONLINE") / len(lista)
            if pct < LIMITES["disponibilidade_pct"]:
                achados.append(Achado(
                    host_id, "Equipamentos",
                    "alta" if pct < LIMITES["disponibilidade_pct_alta"] else "media",
                    f"{nome} ficou offline no período",
                    f"Online em {_num(pct)}% das {len(lista)} verificações.",
                    "Verificar alimentação (PoE/fonte), cabo de uplink e logs do equipamento.",
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
                "Se não houve atualização ou manutenção nesses horários, investigar energia e logs.",
            ))

        com_carga = [a for a in lista if a["cpu_pct"] is not None]
        if len(com_carga) >= LIMITES["carga_min_amostras"]:
            memoria = mean(a["memoria_pct"] for a in com_carga if a["memoria_pct"] is not None)
            cpu = mean(a["cpu_pct"] for a in com_carga)
            if memoria >= LIMITES["memoria_pct"]:
                achados.append(Achado(
                    host_id, "Equipamentos", "media", f"Memória alta em {nome}",
                    f"Uso médio de memória de {_num(memoria)}% em {len(com_carga)} amostras.",
                    "Avaliar aplicações ativas no console e a necessidade de um modelo maior.",
                ))
            if cpu >= LIMITES["cpu_pct"]:
                achados.append(Achado(
                    host_id, "Equipamentos", "media", f"CPU alta em {nome}",
                    f"Uso médio de CPU de {_num(cpu)}% em {len(com_carga)} amostras.",
                    "Avaliar recursos que mais consomem (IDS/IPS, DPI) e a capacidade do equipamento.",
                ))

        if ultima["firmware_atualizavel"]:
            achados.append(Achado(
                host_id, "Equipamentos", "media", f"Firmware desatualizado em {nome}",
                f"{nome} está no firmware {ultima['firmware']} e há atualização disponível.",
                "Atualizar numa janela de manutenção.",
            ))
    return achados


def regra_portas(conexao, inicio, fim):
    """Porta ativa negociando abaixo da capacidade, de forma persistente."""
    achados = []
    janela = max(inicio, fim - timedelta(days=LIMITES["porta_dias"]))
    equipamentos = _ultimos_equipamentos(conexao)
    portas = defaultdict(list)
    for p in _no_periodo(conexao, "SELECT * FROM porta_estado", janela, fim):
        if p["estado"] == "UP":
            portas[(p["device_id"], p["idx"])].append(p)

    for (device_id, idx), lista in sorted(portas.items()):
        if len(lista) < LIMITES["porta_min_amostras"] or device_id not in equipamentos:
            continue
        abaixo = [p for p in lista if (p["velocidade_mbps"] or 0) < (p["velocidade_max_mbps"] or 0)]
        if len(abaixo) / len(lista) < LIMITES["porta_fracao_abaixo"]:
            continue
        e = equipamentos[device_id]
        achados.append(Achado(
            e["host_id"], "Equipamentos", "media",
            f"Porta {idx} de {e['nome']} abaixo da capacidade",
            f"Negociando a {abaixo[-1]['velocidade_mbps']} Mbps (capacidade de "
            f"{abaixo[-1]['velocidade_max_mbps']} Mbps) em {len(abaixo)} de {len(lista)} verificações.",
            "Verificar cabo e conectores. Se o equipamento ligado for antigo ou estiver em modo de "
            "economia de energia, pode ser esperado.",
        ))
    return achados


def regra_radios(conexao, inicio, fim):
    """Retransmissão alta, rádio sem canal e largura de canal inadequada em 2.4 GHz."""
    achados = []
    equipamentos = _ultimos_equipamentos(conexao)

    retransmissao = defaultdict(list)
    for r in _no_periodo(conexao, "SELECT * FROM radio_amostra", inicio, fim):
        if r["retransmissao_pct"] is not None:
            retransmissao[(r["device_id"], r["posicao"], r["frequencia_ghz"])].append(r["retransmissao_pct"])
    for (device_id, _pos, freq), valores in retransmissao.items():
        if len(valores) < LIMITES["retransmissao_min_amostras"] or device_id not in equipamentos:
            continue
        if mean(valores) >= LIMITES["retransmissao_pct"]:
            e = equipamentos[device_id]
            achados.append(Achado(
                e["host_id"], "Wi-Fi", "media", f"Wi-Fi {freq:g} GHz com muita retransmissão em {e['nome']}",
                f"Retransmissão média de {_num(mean(valores))}% em {len(valores)} amostras.",
                "Revisar canal e potência, interferência de redes vizinhas e posicionamento do AP.",
            ))

    for device_id, e in equipamentos.items():
        for r in conexao.execute(
            "SELECT * FROM radio_config WHERE device_id = ? AND coletado_em = "
            "(SELECT MAX(coletado_em) FROM radio_config WHERE device_id = ?)", (device_id, device_id)
        ):
            freq = f"{r['frequencia_ghz']:g} GHz"
            if not r["canal"]:
                achados.append(Achado(
                    e["host_id"], "Wi-Fi", "info", f"Rádio {freq} de {e['nome']} sem canal ativo",
                    f"O rádio {freq} não informa canal; provavelmente está desligado.",
                    "Se for intencional, desconsiderar. Muitos dispositivos IoT (câmeras, impressoras, "
                    "automação) só funcionam em 2.4 GHz.",
                ))
            elif r["frequencia_ghz"] and r["frequencia_ghz"] < 3 and (r["largura_mhz"] or 0) > 20:
                achados.append(Achado(
                    e["host_id"], "Wi-Fi", "media", f"Canal largo demais no 2.4 GHz de {e['nome']}",
                    f"Rádio 2.4 GHz configurado com {r['largura_mhz']} MHz.",
                    "Usar 20 MHz no 2.4 GHz reduz interferência com redes vizinhas.",
                ))
    return achados


# ---------------------------------------------------------------- execução

REGRAS = [
    regra_wan_sem_dado, regra_wan_perda, regra_wan_latencia,
    regra_console_offline, regra_console_disponibilidade, regra_backup, regra_atualizacao_console,
    regra_equipamentos, regra_portas, regra_radios,
]


def avaliar(conexao, inicio, fim):
    """Roda todas as regras no período. Devolve (achados, erros)."""
    achados, erros = [], []
    for regra in REGRAS:
        try:
            achados.extend(regra(conexao, inicio, fim))
        except Exception as erro:  # uma regra com problema não derruba as outras
            erros.append(f"{regra.__name__}: {erro.__class__.__name__}: {erro}")
    achados.sort(key=lambda a: (ORDEM_SEVERIDADE[a.severidade], AREAS.index(a.area)))
    return achados, erros

