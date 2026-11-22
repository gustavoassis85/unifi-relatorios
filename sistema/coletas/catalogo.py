"""Tradução dos códigos da UniFi pelos catálogos (mesma regra do relatório do MVP)."""
from .models import Catalogo

NAO_IDENTIFICADO_APP = 65535
NAO_IDENTIFICADO_CAT = 255


class Nomes:
    def __init__(self):
        self.aplicativos = dict(Catalogo.objects.filter(tipo="dpi_aplicativo").values_list("id_unifi", "nome"))
        self.categorias = dict(Catalogo.objects.filter(tipo="dpi_categoria").values_list("id_unifi", "nome"))

    def aplicativo(self, categoria, aplicativo):
        """No catálogo, o id do aplicativo junta a categoria: (categoria << 16) | aplicativo."""
        if aplicativo == NAO_IDENTIFICADO_APP or categoria == NAO_IDENTIFICADO_CAT:
            return "Não identificado"
        return (self.aplicativos.get((categoria << 16) | aplicativo) or self.aplicativos.get(aplicativo)
                or f"Aplicativo {aplicativo}")

    def categoria(self, categoria):
        if categoria == NAO_IDENTIFICADO_CAT:
            return "Não identificado"
        return self.categorias.get(categoria) or f"Categoria {categoria}"
