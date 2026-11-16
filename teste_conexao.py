"""Teste de conexão com a api.ui.com usando a chave do arquivo .env.

Só faz leitura (GET) e nunca imprime a chave.
Como rodar (com o ambiente virtual ativo):  python teste_conexao.py
"""
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()
chave = os.getenv("UNIFI_API_KEY")
if not chave:
    sys.exit("Chave não encontrada. Confira o arquivo .env (linha UNIFI_API_KEY=...).")

resposta = requests.get(
    "https://api.ui.com/v1/hosts",
    headers={"X-API-Key": chave, "Accept": "application/json"},
    timeout=30,
)

if resposta.status_code == 401:
    sys.exit("Chave recusada (401). Gere uma nova em unifi.ui.com e atualize o .env.")
if resposta.status_code == 429:
    sys.exit("Limite de chamadas atingido (429). Espere um minuto e tente de novo.")
resposta.raise_for_status()

consoles = resposta.json().get("data", [])
print(f"Conexão OK. {len(consoles)} console(s) na conta:")
for host in consoles:
    estado = host.get("reportedState") or {}
    nome = estado.get("name") or "(sem nome)"
    situacao = estado.get("state") or "desconhecido"
    print(f"  - {nome}: {situacao}")
