"""Lista dos modelos que guardam valores cifrados, para a troca da chave mestra.

Cada modelo com credencial declara CAMPOS_CIFRADOS = ["nome_do_campo", ...] e se
registra aqui com registrar(Modelo), no ready() do seu app.
"""
_modelos = []


def registrar(modelo):
    if not getattr(modelo, "CAMPOS_CIFRADOS", None):
        raise ValueError(f"{modelo.__name__} não declara CAMPOS_CIFRADOS.")
    if modelo not in _modelos:
        _modelos.append(modelo)
    return modelo


def modelos_cifrados():
    return list(_modelos)
