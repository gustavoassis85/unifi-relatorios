"""manage.py trabalhador — executa as tarefas em segundo plano (coletas e, depois, PDFs e e-mails).

Roda até Ctrl+C. Ao receber Ctrl+C, termina a tarefa atual antes de sair.
Conecta ao banco como o usuário da aplicação (o mesmo do site).
"""
import logging
import signal
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from tarefas.fila import executar, pegar_proxima, recuperar_travadas
from tarefas.periodicas import rodar_periodicas

log = logging.getLogger("tarefas")

ESPERA_SEM_TAREFA = 5  # segundos


class Command(BaseCommand):
    help = "Executa as tarefas em segundo plano até Ctrl+C."

    def handle(self, *args, **opcoes):
        self.parar = False

        def pedir_parada(*_):
            if not self.parar:
                self.stdout.write("Parando: termina a tarefa atual e sai.")
            self.parar = True

        signal.signal(signal.SIGINT, pedir_parada)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, pedir_parada)

        self.stdout.write("Trabalhador rodando. Ctrl+C para parar.")
        while not self.parar:
            close_old_connections()
            try:
                recuperar_travadas()
                for nome in rodar_periodicas():
                    self.stdout.write(f"Periódica disparada: {nome}")
                tarefa = pegar_proxima()
            except Exception:  # noqa: BLE001 - banco fora do ar, por exemplo: espera e tenta de novo
                log.exception("Erro no laço do trabalhador")
                tarefa = None
            if tarefa is None:
                for _ in range(ESPERA_SEM_TAREFA * 10):
                    if self.parar:
                        break
                    time.sleep(0.1)
                continue
            self.stdout.write(f"Rodando {tarefa.tipo} #{tarefa.pk}")
            executar(tarefa)
            tarefa.refresh_from_db()
            self.stdout.write(f"  {tarefa.get_situacao_display()}{': ' + tarefa.erro if tarefa.erro else ''}")
        self.stdout.write("Trabalhador parado.")
