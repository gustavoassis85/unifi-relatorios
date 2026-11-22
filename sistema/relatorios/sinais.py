"""Avisos do app de relatórios para outros apps (o envio por e-mail escuta o relatorio_pronto)."""
from django.dispatch import Signal

# Enviado pelo trabalhador quando o relatório fica pronto (HTML e PDF gravados). Argumento: relatorio.
relatorio_pronto = Signal()
