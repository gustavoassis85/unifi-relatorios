"""Ícones genéricos por categoria de tráfego (traço simples, cor do tema).

Não usamos logotipos de aplicativos: são marcas de cada empresa. O ícone indica o tipo de tráfego.
"""

_TRACOS = {
    "streaming": '<rect x="1.5" y="3" width="13" height="10" rx="2"/><path d="M6.5 6v4l3.5-2z" class="cheio"/>',
    "mensagem": '<path d="M2.5 3.5h11v7h-6l-3 2.5v-2.5h-2z"/>',
    "email": '<rect x="2" y="4" width="12" height="8" rx="1"/><path d="M2.5 4.5 8 9l5.5-4.5"/>',
    "atualizacao": '<path d="M13 8a5 5 0 1 1-1.46-3.54"/><path d="M13 2.5v3h-3"/>',
    "web": '<circle cx="8" cy="8" r="5.5"/><path d="M2.5 8h11M8 2.5c2.2 2.2 2.2 8.8 0 11M8 2.5c-2.2 2.2-2.2 8.8 0 11"/>',
    "rede": ('<circle cx="4" cy="8" r="1.6"/><circle cx="12" cy="4" r="1.6"/><circle cx="12" cy="12" r="1.6"/>'
             '<path d="M5.4 7.3l5.2-2.6M5.4 8.7l5.2 2.6"/>'),
    "arquivo": '<path d="M2 4.5h4l1.5 1.5H14v6.5H2z"/>',
    "voz": '<path d="M5 2.5h2l1 3-1.5 1a7 7 0 0 0 3 3l1-1.5 3 1v2a1.5 1.5 0 0 1-1.5 1.5A10 10 0 0 1 3.5 4 1.5 1.5 0 0 1 5 2.5z"/>',
    "jogo": '<rect x="1.5" y="5" width="13" height="7" rx="3.5"/><path d="M4.5 8.5h3M6 7v3"/><circle cx="11" cy="8.5" r=".8" class="cheio"/>',
    "seguranca": '<path d="M8 2l5 2v4c0 3-2.2 5-5 6-2.8-1-5-3-5-6V4z"/>',
    "desconhecido": '<circle cx="8" cy="8" r="5.5"/><path d="M6.4 6.4a1.6 1.6 0 1 1 2.3 1.4c-.5.3-.7.6-.7 1.2"/><circle cx="8" cy="10.9" r=".6" class="cheio"/>',
    "outros": ('<rect x="3" y="3" width="4" height="4" rx="1"/><rect x="9" y="3" width="4" height="4" rx="1"/>'
               '<rect x="3" y="9" width="4" height="4" rx="1"/><rect x="9" y="9" width="4" height="4" rx="1"/>'),
}

# Palavras do nome da categoria (inglês do catálogo ou português) -> ícone. A ordem importa.
_REGRAS = [
    (("não identificado", "unknown"), "desconhecido"),
    (("mail",), "email"),
    (("stream", "vídeo", "video"), "streaming"),
    (("messeng", "mensage", "social", "redes sociais"), "mensagem"),
    (("update", "atualiza"), "atualizacao"),
    (("voip", "voz", "conferenc"), "voz"),
    (("game", "jogo"), "jogo"),
    (("file", "arquivo", "storage", "nuvem", "p2p", "peer"), "arquivo"),
    (("security", "segurança", "proxy", "proxies", "tunnel", "túne", "vpn"), "seguranca"),
    (("network", "protocol", "rede", "remote", "remoto"), "rede"),
    (("web", "http", "browser"), "web"),
]


def icone(categoria):
    """SVG inline de 16 px para o nome da categoria."""
    nome = (categoria or "").lower()
    chave = next((icone for palavras, icone in _REGRAS if any(p in nome for p in palavras)), "outros")
    return (f'<svg class="icone" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">'
            f'{_TRACOS[chave]}</svg>')
