import base64


from organizacoes.isolamento import exigir_organizacao
from organizacoes.models import Organizacao

from .models import Marca, Tema


def marca_da_organizacao():
    """A marca salva ou, se ainda não há, uma com o nome da organização (não gravada)."""
    marca = Marca.objects.first()
    if marca is None:
        marca = Marca(empresa=Organizacao.objects.get(pk=exigir_organizacao()).nome, tema=Tema.ESCURO)
    return marca


def logo_embutido(marca):
    """O logo como endereço data: (para a prévia na tela e para o relatório). Vazio se não há."""
    if not marca.logo:
        return ""
    return "data:image/png;base64," + base64.b64encode(bytes(marca.logo)).decode("ascii")


