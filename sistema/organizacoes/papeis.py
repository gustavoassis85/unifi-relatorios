"""O que cada papel pode fazer dentro da própria organização.

Toda tela consulta estas funções; nenhuma decide a permissão por conta própria.
"""
from .models import Papel


def pode_ver_clientes(papel):
    return papel in (Papel.ADMIN, Papel.OPERADOR, Papel.LEITURA)


def pode_editar_clientes(papel):
    """Criar, editar e apagar clientes."""
    return papel in (Papel.ADMIN, Papel.OPERADOR)


def pode_gerenciar_usuarios(papel):
    """Criar, desativar e mudar o papel de usuários da própria organização."""
    return papel == Papel.ADMIN


def pode_gerenciar_chaves(papel):
    """Cadastrar, trocar e apagar a chave da UniFi de um cliente."""
    return papel == Papel.ADMIN


def pode_testar_conexao(papel):
    """Testar a conexão com a UniFi e escolher quais consoles acompanhar."""
    return papel in (Papel.ADMIN, Papel.OPERADOR)


def pode_editar_marca(papel):
    """Nome, contato, logo e tema dos relatórios da organização."""
    return papel == Papel.ADMIN


def pode_gerar_relatorio(papel):
    return papel in (Papel.ADMIN, Papel.OPERADOR)


def exige_mfa(papel):
    return papel == Papel.ADMIN
