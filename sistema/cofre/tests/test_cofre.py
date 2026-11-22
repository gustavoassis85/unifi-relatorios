"""Testes do cofre: criptografia, troca da chave mestra, configuração e páginas de erro."""
import importlib.util
import os
import pathlib
import subprocess
import sys

import pytest
from cryptography.fernet import Fernet
from django.test import RequestFactory

from cofre.cifra import ErroCofre, cifrar, decifrar, recifrar, ultimos4, validar_chave_mestra
from cofre.filtro_erros import FiltroDeErros

SEGREDO = "chave-de-teste-ABCDEFGH-1234-wxyz"
RAIZ = pathlib.Path(__file__).resolve().parents[2]


def test_cifra_e_decifra_sem_deixar_o_texto_visivel():
    cifrado = cifrar(SEGREDO)
    assert SEGREDO not in cifrado
    assert "wxyz" not in cifrado
    assert decifrar(cifrado) == SEGREDO


def test_cada_cifra_sai_diferente():
    assert cifrar(SEGREDO) != cifrar(SEGREDO)


def test_nao_cifra_vazio():
    with pytest.raises(ErroCofre):
        cifrar("")


def test_chave_mestra_errada_da_erro_sem_mostrar_segredo(settings):
    cifrado = cifrar(SEGREDO)
    settings.UNIFI_CHAVE_MESTRA = Fernet.generate_key().decode()
    with pytest.raises(ErroCofre) as erro:
        decifrar(cifrado)
    mensagem = str(erro.value)
    assert SEGREDO not in mensagem and cifrado not in mensagem
    assert settings.UNIFI_CHAVE_MESTRA not in mensagem


def test_valor_adulterado_e_recusado():
    cifrado = cifrar(SEGREDO)
    adulterado = cifrado[:-6] + ("A" if cifrado[-6] != "A" else "B") + cifrado[-5:]
    with pytest.raises(ErroCofre):
        decifrar(adulterado)


def test_troca_da_chave_mestra(settings):
    antiga = settings.UNIFI_CHAVE_MESTRA
    cifrado_antigo = cifrar(SEGREDO)

    nova = Fernet.generate_key().decode()
    settings.UNIFI_CHAVE_MESTRA = nova
    settings.UNIFI_CHAVES_MESTRAS_ANTERIORES = [antiga]
    assert decifrar(cifrado_antigo) == SEGREDO  # durante a troca, lê o antigo

    regravado = recifrar(cifrado_antigo)
    settings.UNIFI_CHAVES_MESTRAS_ANTERIORES = []  # fim da troca: a antiga sai
    assert decifrar(regravado) == SEGREDO
    with pytest.raises(ErroCofre):
        decifrar(cifrado_antigo)


def test_ultimos4():
    assert ultimos4(SEGREDO) == "wxyz"
    assert ultimos4("curta") == ""  # muito curta: não mostra nada
    assert ultimos4("") == ""


def test_validar_chave_mestra():
    assert validar_chave_mestra(Fernet.generate_key().decode())
    assert not validar_chave_mestra("nao-e-chave")
    assert not validar_chave_mestra("")


def test_pagina_de_erro_esconde_configuracoes_em_portugues():
    configuracoes = FiltroDeErros().get_safe_settings()
    assert configuracoes["UNIFI_CHAVE_MESTRA"] != os.environ["UNIFI_CHAVE_MESTRA"]
    assert "*" in str(configuracoes["UNIFI_CHAVE_MESTRA"])
    assert os.environ["UNIFI_CHAVE_MESTRA"] not in str(configuracoes)


def test_pagina_de_erro_esconde_campos_de_formulario_com_chave_ou_senha():
    pedido = RequestFactory().post("/x/", {"chave": SEGREDO, "senha_smtp": "s3nh4", "nome": "Loja"})
    campos = FiltroDeErros().get_post_parameters(pedido)
    assert campos["chave"] != SEGREDO
    assert campos["senha_smtp"] != "s3nh4"
    assert campos["nome"] == "Loja"


def _rodar_configuracao(chave):
    ambiente = dict(
        os.environ, UNIFI_CHAVE_MESTRA=chave, DJANGO_SETTINGS_MODULE="config.settings",
        PYTHONIOENCODING="utf-8",
    )
    return subprocess.run(
        [sys.executable, "-c", "import django; django.setup()"],
        cwd=RAIZ, env=ambiente, capture_output=True, text=True, encoding="utf-8", timeout=60,
    )


def test_sistema_nao_sobe_com_chave_mestra_invalida():
    resultado = _rodar_configuracao("chave-invalida-que-nao-pode-aparecer")
    assert resultado.returncode != 0
    assert "UNIFI_CHAVE_MESTRA não é uma chave válida" in resultado.stderr
    assert "chave-invalida-que-nao-pode-aparecer" not in resultado.stderr


def test_sistema_nao_sobe_sem_chave_mestra():
    resultado = _rodar_configuracao("")
    assert resultado.returncode != 0
    assert "UNIFI_CHAVE_MESTRA" in resultado.stderr


@pytest.mark.django_db
def test_recriptografar_sem_credenciais_nao_falha():
    from django.core.management import call_command

    call_command("recriptografar")


# Gerador do .env --------------------------------------------------------------

def _gerador():
    spec = importlib.util.spec_from_file_location("gerar_env", RAIZ / "scripts" / "gerar_env.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_completar_acrescenta_so_o_que_falta(tmp_path, capsys):
    gerador = _gerador()
    arquivo = tmp_path / ".env"
    arquivo.write_text("DJANGO_SECRET_KEY=mantida\nDB_APP_SENHA=mantida2\n", encoding="utf-8")
    gerador.completar(arquivo)
    _, valores = gerador.ler(arquivo)
    assert valores["DJANGO_SECRET_KEY"] == "mantida"
    assert valores["DB_APP_SENHA"] == "mantida2"
    assert validar_chave_mestra(valores["UNIFI_CHAVE_MESTRA"])
    saida = capsys.readouterr().out
    assert valores["UNIFI_CHAVE_MESTRA"] not in saida


def test_trocar_chave_mestra_guarda_a_anterior(tmp_path, capsys):
    gerador = _gerador()
    arquivo = tmp_path / ".env"
    antiga = Fernet.generate_key().decode()
    arquivo.write_text(f"OUTRA=1\nUNIFI_CHAVE_MESTRA={antiga}\n", encoding="utf-8")
    gerador.trocar_chave_mestra(arquivo)
    _, valores = gerador.ler(arquivo)
    assert valores["UNIFI_CHAVE_MESTRA_ANTERIOR"] == antiga
    assert valores["UNIFI_CHAVE_MESTRA"] != antiga
    assert validar_chave_mestra(valores["UNIFI_CHAVE_MESTRA"])
    assert valores["OUTRA"] == "1"
    saida = capsys.readouterr().out
    assert antiga not in saida and valores["UNIFI_CHAVE_MESTRA"] not in saida
    with pytest.raises(SystemExit):  # não começa outra troca antes de terminar esta
        gerador.trocar_chave_mestra(arquivo)
