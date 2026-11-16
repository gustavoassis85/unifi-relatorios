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
"""


def conectar():
    """Abre o banco, criando o arquivo e as tabelas se ainda não existirem."""
    ARQUIVO_BANCO.parent.mkdir(exist_ok=True)
    conexao = sqlite3.connect(ARQUIVO_BANCO)
    conexao.row_factory = sqlite3.Row
    conexao.executescript(TABELAS)
    return conexao
