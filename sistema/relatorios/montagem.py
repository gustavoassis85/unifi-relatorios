"""Monta o relatório de um cliente: pontos de atenção, higiene da conta e HTML com a marca."""
from dataclasses import dataclass

from conexoes.models import Console

from .achados import avaliar
from .fonte import Fonte
from .modelo.gerar import gerar_html
from .servicos import logo_embutido, marca_da_organizacao


@dataclass
class Montado:
    html: str
    higiene: list      # achados da área Conta: só o MSP vê, fora do relatório do cliente
    erros: list        # regras que falharam (o relatório sai mesmo assim)


def montar(cliente, inicio, fim):
    """Precisa rodar no contexto da organização do cliente."""
    consoles_da_conta = list(Console.objects.filter(cliente=cliente))
    fonte = Fonte(cliente, [c for c in consoles_da_conta if c.acompanhar])
    achados, higiene, erros = avaliar(fonte, inicio, fim, consoles_da_conta)
    marca = marca_da_organizacao()
    dados_marca = {"empresa": marca.empresa, "contato": marca.contato, "tema": marca.tema,
                   "logo": logo_embutido(marca)}
    return Montado(gerar_html(fonte, achados, inicio, fim, dados_marca), higiene, erros)
