"""PDF do relatório com o Playwright (Chromium sem tela).

O Chromium fica em sistema/.navegadores (instalado com:
  set PLAYWRIGHT_BROWSERS_PATH=.navegadores && python -m playwright install chromium-headless-shell).
Travas na geração: JavaScript desligado, sem rede (modo offline e toda requisição abortada;
imagens embutidas em data: continuam funcionando) e tempo limite de 60 s.
"""
import logging
import os
from pathlib import Path

from django.conf import settings

PASTA_NAVEGADORES = Path(settings.BASE_DIR) / ".navegadores"
TEMPO_LIMITE_MS = 60_000
log = logging.getLogger("relatorios")


class ErroPdf(Exception):
    pass


def _abrir(html, acao):
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(PASTA_NAVEGADORES))
    from playwright.sync_api import Error as ErroPlaywright
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch(headless=True)
            try:
                contexto = navegador.new_context(java_script_enabled=False, offline=True)
                contexto.set_default_timeout(TEMPO_LIMITE_MS)
                pagina = contexto.new_page()
                pagina.route("**/*", lambda rota: rota.abort())
                pagina.set_content(html, wait_until="load")
                return acao(pagina)
            finally:
                navegador.close()
    except ErroPlaywright as erro:
        # O texto do Playwright pode ter caminhos do servidor: vai só para o log; o MSP vê o resumo.
        log.warning("Falha do Chromium ao gerar o PDF: %s", erro)
        texto = str(erro)
        if "Timeout" in texto:
            motivo = "passou do tempo limite de 60 s"
        elif "Executable doesn't exist" in texto:
            motivo = "o Chromium não está instalado no servidor"
        else:
            motivo = "falha no Chromium"
        raise ErroPdf(f"Não foi possível gerar o PDF ({motivo}).") from None


def gerar_pdf(html):
    return _abrir(html, lambda pagina: pagina.pdf(format="A4", print_background=True, prefer_css_page_size=True))


def gerar_imagem(html, largura=1100):
    """Imagem da página inteira (para conferência visual, não vai para o cliente)."""
    def capturar(pagina):
        pagina.set_viewport_size({"width": largura, "height": 900})
        return pagina.screenshot(full_page=True)

    return _abrir(html, capturar)
