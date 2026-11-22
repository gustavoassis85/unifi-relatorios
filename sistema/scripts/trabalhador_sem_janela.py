"""Roda o `manage.py trabalhador` sem janela, gravando tudo em sistema/logs/trabalhador.log.

Feito para o Agendador de Tarefas do Windows (com pythonw.exe, que não abre janela):
  .venv\\Scripts\\pythonw.exe scripts\\trabalhador_sem_janela.py
Para parar: no Agendador, "Finalizar" a tarefa "Dashboard UniFi - Trabalhador".
Uma tarefa interrompida no meio volta para a fila sozinha (recuperar_travadas).
"""
import logging
import os
import sys
from pathlib import Path

PASTA = Path(__file__).resolve().parent.parent
LOGS = PASTA / "logs"
ARQUIVO = LOGS / "trabalhador.log"
TAMANHO_MAXIMO = 5 * 1024 * 1024   # passou disso, o log atual vira trabalhador.log.1


def main():
    LOGS.mkdir(exist_ok=True)
    if ARQUIVO.exists() and ARQUIVO.stat().st_size > TAMANHO_MAXIMO:
        ARQUIVO.replace(ARQUIVO.with_suffix(".log.1"))
    saida = open(ARQUIVO, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = saida
    logging.basicConfig(stream=saida, level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    os.chdir(PASTA)
    sys.path.insert(0, str(PASTA))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    logging.getLogger("tarefas").info("Iniciado pelo lançador sem janela")
    execute_from_command_line(["manage.py", "trabalhador"])


if __name__ == "__main__":
    main()
