"""Validação do logo enviado pelo MSP.

O arquivo é conferido pelo conteúdo (não pela extensão), aberto pela Pillow e regravado
como PNG novo, reduzido para no máximo 600 x 200 pixels. Regravar descarta tudo que não
é imagem (metadados, conteúdo escondido no fim do arquivo). SVG não é aceito: pode ter código.
"""
import io

from PIL import Image, UnidentifiedImageError

TAMANHO_MAXIMO = 500 * 1024          # bytes do arquivo enviado
PIXELS_MAXIMOS = 25_000_000          # contra imagem "bomba" (pequena no disco, enorme na memória)
CAIXA = (600, 200)
ASSINATURAS = {b"\x89PNG\r\n\x1a\n": "PNG", b"\xff\xd8\xff": "JPEG"}


class LogoInvalido(ValueError):
    pass


def preparar_logo(arquivo):
    """Recebe o arquivo enviado e devolve os bytes do PNG regravado."""
    if arquivo.size > TAMANHO_MAXIMO:
        raise LogoInvalido("O logo pode ter no máximo 500 KB.")
    dados = arquivo.read(TAMANHO_MAXIMO + 1)
    formato = next((f for assinatura, f in ASSINATURAS.items() if dados.startswith(assinatura)), None)
    if formato is None:
        raise LogoInvalido("Envie o logo em PNG ou JPG.")
    try:
        with Image.open(io.BytesIO(dados)) as imagem:
            if imagem.format != formato:
                raise LogoInvalido("Envie o logo em PNG ou JPG.")
            largura, altura = imagem.size
            if largura * altura > PIXELS_MAXIMOS:
                raise LogoInvalido("A imagem do logo é grande demais.")
            imagem.load()
            imagem = imagem.convert("RGBA")
            imagem.thumbnail(CAIXA)
            saida = io.BytesIO()
            imagem.save(saida, format="PNG", optimize=True)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError):
        raise LogoInvalido("Não foi possível abrir a imagem. Envie o logo em PNG ou JPG.") from None
    return saida.getvalue()
