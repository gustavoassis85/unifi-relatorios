"""Periódicas da própria fila."""
from .fila import apagar_antigas
from .periodicas import periodica


@periodica("limpar_tarefas", hora=3, minuto=15)
def limpar_tarefas(agora):
    apagar_antigas(agora)
