"""Banco de dados do projeto.

No desenvolvimento, o banco é o arquivo dados/unifi.db (a pasta dados/ fica fora do Git).
As tabelas são criadas automaticamente na primeira vez.
"""
import sqlite3
from pathlib import Path

ARQUIVO_BANCO = Path(__file__).resolve().parent.parent / "dados" / "unifi.db"

TABELAS = """
CREATE TABLE IF NOT EXISTS wan_hora (
    host_id        TEXT NOT NULL,   -- console (id da Site Manager)
    site_id        TEXT NOT NULL,   -- site (id da Site Manager)
    horario        TEXT NOT NULL,   -- início da hora, em UTC
    latencia_media REAL,            -- ms
    latencia_max   REAL,            -- ms
    perda_pct      REAL,            -- perda de pacote, %
    uptime_pct     REAL,            -- %
    downtime       REAL,
    download_kbps  INTEGER,         -- velocidade do plano, não é tráfego
    upload_kbps    INTEGER,         -- velocidade do plano, não é tráfego
    provedor       TEXT,
    asn            TEXT,
    coletado_em    TEXT NOT NULL,   -- quando o coletor gravou, em UTC
    PRIMARY KEY (host_id, site_id, horario)
);

CREATE TABLE IF NOT EXISTS console_estado (
    host_id                TEXT NOT NULL,   -- console (id da Site Manager)
    coletado_em            TEXT NOT NULL,   -- quando o coletor gravou, em UTC
    nome                   TEXT,
    modelo                 TEXT,
    tipo                   TEXT,            -- console ou network-server
    conectado              INTEGER,         -- 1 = conectado à nuvem, 0 = não
    estado                 TEXT,            -- valor original da API
    versao_os              TEXT,            -- versão interna do UniFi OS (só consoles)
    firmware               TEXT,            -- versão que o Site Manager mostra (ex.: 5.1.19)
    versao_network         TEXT,            -- aplicação Network
    atualizacao_disponivel TEXT,            -- versão nova do UniFi OS, se houver
    ultimo_backup          TEXT,            -- último backup em nuvem, em UTC
    mudou_estado_em        TEXT,            -- última troca conectado/desconectado, em UTC
    wans_conectadas        INTEGER,
    PRIMARY KEY (host_id, coletado_em)
);

-- Sites vistos pela API Network (o id aqui é o UUID da Network, diferente da Site Manager).
CREATE TABLE IF NOT EXISTS site_network (
    host_id       TEXT NOT NULL,
    site_id       TEXT NOT NULL,
    nome          TEXT,
    referencia    TEXT,            -- internalReference (ex.: default)
    atualizado_em TEXT NOT NULL,
    PRIMARY KEY (host_id, site_id)
);

-- Foto de cada equipamento a cada coleta.
CREATE TABLE IF NOT EXISTS equipamento_amostra (
    host_id              TEXT NOT NULL,
    site_id              TEXT NOT NULL,
    device_id            TEXT NOT NULL,
    coletado_em          TEXT NOT NULL,
    nome                 TEXT,
    modelo               TEXT,
    mac                  TEXT,
    ip                   TEXT,
    estado               TEXT,     -- ONLINE, OFFLINE...
    firmware             TEXT,
    firmware_atualizavel INTEGER,  -- 1 = o Network oferece atualização
    uptime_seg           INTEGER,
    cpu_pct              REAL,
    memoria_pct          REAL,
    carga_1min           REAL,
    uplink_tx_bps        INTEGER,  -- taxa no momento da coleta, não é volume
    uplink_rx_bps        INTEGER,
    PRIMARY KEY (device_id, coletado_em)
);

-- Retransmissão de cada rádio a cada coleta.
CREATE TABLE IF NOT EXISTS radio_amostra (
    device_id         TEXT NOT NULL,
    coletado_em       TEXT NOT NULL,
    posicao           INTEGER NOT NULL,  -- ordem do rádio no equipamento
    frequencia_ghz    REAL,
    retransmissao_pct REAL,
    PRIMARY KEY (device_id, coletado_em, posicao)
);

-- Detalhe do equipamento (1x por dia): configuração, portas e rádios.
CREATE TABLE IF NOT EXISTS equipamento_detalhe (
    device_id       TEXT NOT NULL,
    coletado_em     TEXT NOT NULL,
    configuracao_id TEXT,
    provisionado_em TEXT,              -- último envio de configuração, não é a instalação
    PRIMARY KEY (device_id, coletado_em)
);

CREATE TABLE IF NOT EXISTS porta_estado (
    device_id           TEXT NOT NULL,
    coletado_em         TEXT NOT NULL,
    idx                 INTEGER NOT NULL,
    estado              TEXT,          -- UP ou DOWN
    conector            TEXT,
    velocidade_mbps     INTEGER,       -- negociada (porta DOWN mostra um valor sem sentido)
    velocidade_max_mbps INTEGER,
    poe_padrao          TEXT,
    poe_ativo           INTEGER,
    poe_estado          TEXT,
    PRIMARY KEY (device_id, coletado_em, idx)
);

CREATE TABLE IF NOT EXISTS radio_config (
    device_id      TEXT NOT NULL,
    coletado_em    TEXT NOT NULL,
    posicao        INTEGER NOT NULL,
    frequencia_ghz REAL,
    padrao         TEXT,               -- 802.11n, 802.11ax...
    largura_mhz    INTEGER,
    canal          INTEGER,
    PRIMARY KEY (device_id, coletado_em, posicao)
);

-- Quantidade de clientes conectados em cada site, a cada coleta.
CREATE TABLE IF NOT EXISTS clientes_amostra (
    host_id     TEXT NOT NULL,
    site_id     TEXT NOT NULL,
    coletado_em TEXT NOT NULL,
    total       INTEGER,
    cabo        INTEGER,
    wifi        INTEGER,
    PRIMARY KEY (host_id, site_id, coletado_em)
);
"""


# Colunas acrescentadas depois que o banco já existia: (tabela, coluna, tipo).
COLUNAS_NOVAS = [
    ("console_estado", "firmware", "TEXT"),
]


def _migrar(conexao):
    """Acrescenta colunas novas em bancos criados por versões anteriores do projeto."""
    for tabela, coluna, tipo in COLUNAS_NOVAS:
        existentes = {linha[1] for linha in conexao.execute(f"PRAGMA table_info({tabela})")}
        if coluna not in existentes:
            conexao.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
    conexao.commit()


def conectar():
    """Abre o banco, criando o arquivo e as tabelas se ainda não existirem."""
    ARQUIVO_BANCO.parent.mkdir(exist_ok=True)
    conexao = sqlite3.connect(ARQUIVO_BANCO)
    conexao.row_factory = sqlite3.Row
    conexao.executescript(TABELAS)
    _migrar(conexao)
    return conexao
