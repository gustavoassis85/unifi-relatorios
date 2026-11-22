"""Cria ou completa o sistema/.env com valores aleatórios. Nunca mostra nenhum valor na tela.

Uso (dentro de sistema/):
  python scripts\\gerar_env.py                        cria o .env (se ainda não existe)
  python scripts\\gerar_env.py --completar            acrescenta só as linhas que faltam
  python scripts\\gerar_env.py --trocar-chave-mestra  gera uma chave mestra nova e guarda a
                                                      atual como anterior; depois rode
                                                      manage.py recriptografar
"""
import base64
import os
import pathlib
import secrets
import sys

ARQUIVO = pathlib.Path(__file__).resolve().parent.parent / ".env"


def nova_chave_mestra():
    # Mesmo formato do Fernet.generate_key(): 32 bytes aleatórios em base64 de URL.
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


def valores_novos():
    return {
        "DJANGO_SECRET_KEY": secrets.token_urlsafe(50),
        "DJANGO_DEBUG": "0",
        "DJANGO_ALLOWED_HOSTS": "localhost,127.0.0.1",
        "DJANGO_ADMIN_URL": "plataforma-" + secrets.token_hex(6) + "/",
        "DJANGO_HTTPS": "0",
        "DB_NOME": "unifi_sistema",
        "DB_HOST": "localhost",
        "DB_PORTA": "5432",
        "DB_DONO_USUARIO": "unifi_dono",
        "DB_DONO_SENHA": secrets.token_urlsafe(32),
        "DB_APP_USUARIO": "unifi_app",
        "DB_APP_SENHA": secrets.token_urlsafe(32),
        "UNIFI_CHAVE_MESTRA": nova_chave_mestra(),
    }


def ler(arquivo):
    """Linhas do .env na ordem, e um dicionário nome -> valor."""
    linhas = arquivo.read_text(encoding="utf-8").splitlines()
    valores = {}
    for linha in linhas:
        if "=" in linha and not linha.lstrip().startswith("#"):
            nome, valor = linha.split("=", 1)
            valores[nome.strip()] = valor.strip()
    return linhas, valores


def gravar(arquivo, linhas):
    arquivo.write_text("".join(linha + "\n" for linha in linhas), encoding="utf-8")


def criar(arquivo):
    if arquivo.exists():
        sys.exit("sistema/.env já existe; nada foi alterado. Para acrescentar o que falta: --completar")
    valores = valores_novos()
    gravar(arquivo, [f"{k}={v}" for k, v in valores.items()])
    print("sistema/.env criado. Tamanho de cada valor:", {k: len(v) for k, v in valores.items()})


def completar(arquivo):
    if not arquivo.exists():
        sys.exit("sistema/.env não existe. Rode sem opções para criar.")
    linhas, atuais = ler(arquivo)
    faltando = {k: v for k, v in valores_novos().items() if not atuais.get(k)}
    linhas = [l for l in linhas if not (l.split("=", 1)[0].strip() in faltando and "=" in l)]
    gravar(arquivo, linhas + [f"{k}={v}" for k, v in faltando.items()])
    print("Linhas acrescentadas:", sorted(faltando) or "nenhuma")


def trocar_chave_mestra(arquivo):
    if not arquivo.exists():
        sys.exit("sistema/.env não existe.")
    linhas, atuais = ler(arquivo)
    atual = atuais.get("UNIFI_CHAVE_MESTRA")
    if not atual:
        sys.exit("Não há UNIFI_CHAVE_MESTRA no .env. Use --completar.")
    if atuais.get("UNIFI_CHAVE_MESTRA_ANTERIOR"):
        sys.exit(
            "Já existe UNIFI_CHAVE_MESTRA_ANTERIOR: termine a troca anterior "
            "(manage.py recriptografar e apague essa linha) antes de começar outra."
        )
    novas = [l for l in linhas if l.split("=", 1)[0].strip() != "UNIFI_CHAVE_MESTRA"]
    novas += [f"UNIFI_CHAVE_MESTRA={nova_chave_mestra()}", f"UNIFI_CHAVE_MESTRA_ANTERIOR={atual}"]
    gravar(arquivo, novas)
    print(
        "Chave mestra nova gravada; a atual ficou como UNIFI_CHAVE_MESTRA_ANTERIOR.\n"
        "Agora rode: .venv\\Scripts\\python.exe manage.py recriptografar\n"
        "Depois apague a linha UNIFI_CHAVE_MESTRA_ANTERIOR do .env."
    )


if __name__ == "__main__":
    opcao = sys.argv[1] if len(sys.argv) > 1 else ""
    acoes = {"": criar, "--completar": completar, "--trocar-chave-mestra": trocar_chave_mestra}
    if opcao not in acoes:
        sys.exit(__doc__)
    acoes[opcao](ARQUIVO)
