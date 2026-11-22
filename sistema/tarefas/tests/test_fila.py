"""Fila de tarefas, trabalhador e periódicas."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
import pytest
from django.db import connection
from django.utils import timezone

from clientes.models import Cliente
from organizacoes.isolamento import contexto
from tarefas import fila, periodicas
from tarefas.fila import ErroDefinitivo, ErroTemporario, enfileirar, executar, pegar_proxima, tarefa
from tarefas.models import Periodica, Situacao, Tarefa

SP = ZoneInfo("America/Sao_Paulo")
vistos = []


@tarefa("teste_ok")
def _ok(t):
    vistos.append(("ok", t.pk))


@tarefa("teste_definitivo")
def _definitivo(t):
    raise ErroDefinitivo("Chave recusada.")


@tarefa("teste_temporario")
def _temporario(t):
    raise ErroTemporario("Falha de rede.")


@tarefa("teste_inesperado")
def _inesperado(t):
    raise RuntimeError("detalhe-interno-que-nao-pode-sair")


@tarefa("teste_clientes")
def _clientes(t):
    sem_contexto = list(Cliente.objects.values_list("nome", flat=True))
    with contexto(organizacao_id=t.organizacao_id):
        com_contexto = list(Cliente.objects.values_list("nome", flat=True))
    vistos.append((sem_contexto, com_contexto))


@pytest.fixture(autouse=True)
def limpar_vistos():
    vistos.clear()


def recarregar(t):
    return Tarefa.objects.get(pk=t.pk)


# Fila -----------------------------------------------------------------------------

@pytest.mark.django_db
def test_exclusiva_nao_duplica_na_fila_mas_libera_depois_de_feita():
    primeira = enfileirar("teste_ok", exclusiva="x:1")
    assert primeira is not None
    assert enfileirar("teste_ok", exclusiva="x:1") is None
    executar(pegar_proxima())
    assert recarregar(primeira).situacao == Situacao.FEITA
    assert enfileirar("teste_ok", exclusiva="x:1") is not None


@pytest.mark.django_db
def test_tipo_desconhecido_e_recusado():
    with pytest.raises(ValueError):
        enfileirar("nao_existe")


@pytest.mark.django_db
def test_pega_na_ordem_e_so_as_vencidas():
    agora = timezone.now()
    futura = enfileirar("teste_ok", executar_em=agora + timedelta(minutes=5))
    primeira = enfileirar("teste_ok", executar_em=agora - timedelta(minutes=2))
    segunda = enfileirar("teste_ok", executar_em=agora - timedelta(minutes=1))
    assert pegar_proxima(agora).pk == primeira.pk
    assert pegar_proxima(agora).pk == segunda.pk
    assert pegar_proxima(agora) is None
    reservada = recarregar(primeira)
    assert reservada.situacao == Situacao.RODANDO and reservada.tentativas == 1
    assert recarregar(futura).situacao == Situacao.FILA


@pytest.mark.django_db
def test_sucesso():
    t = enfileirar("teste_ok")
    executar(pegar_proxima())
    t = recarregar(t)
    assert t.situacao == Situacao.FEITA and t.terminada_em and t.erro == ""
    assert vistos == [("ok", t.pk)]


@pytest.mark.django_db
def test_erro_definitivo_nao_tenta_de_novo():
    t = enfileirar("teste_definitivo")
    executar(pegar_proxima())
    t = recarregar(t)
    assert t.situacao == Situacao.FALHOU and t.erro == "Chave recusada." and t.tentativas == 1


@pytest.mark.django_db
def test_erro_temporario_tenta_de_novo_com_espera_e_desiste_no_maximo():
    t = enfileirar("teste_temporario", max_tentativas=3)
    executar(pegar_proxima())
    t = recarregar(t)
    assert t.situacao == Situacao.FILA and t.erro == "Falha de rede."
    assert t.executar_em > timezone.now() + timedelta(minutes=1)

    for _ in range(2):
        executar(pegar_proxima(t.executar_em + timedelta(hours=1)))
        t = recarregar(t)
    assert t.situacao == Situacao.FALHOU and t.tentativas == 3


@pytest.mark.django_db
def test_erro_inesperado_guarda_so_o_tipo_do_erro():
    t = enfileirar("teste_inesperado", max_tentativas=1)
    executar(pegar_proxima())
    t = recarregar(t)
    assert t.situacao == Situacao.FALHOU
    assert t.erro == "Erro inesperado (RuntimeError)."
    assert "detalhe-interno" not in t.erro


@pytest.mark.django_db
def test_tarefa_so_ve_a_propria_organizacao_e_so_dentro_do_contexto(msps):
    enfileirar("teste_clientes", organizacao_id=msps.org_a.pk)
    executar(pegar_proxima())
    assert vistos == [([], ["Padaria do A"])]


@pytest.mark.django_db
def test_travada_volta_para_a_fila():
    t = enfileirar("teste_ok")
    pegar_proxima()
    assert fila.recuperar_travadas(timezone.now() + timedelta(minutes=10)) == 0
    assert fila.recuperar_travadas(timezone.now() + timedelta(minutes=31)) == 1
    t = recarregar(t)
    assert t.situacao == Situacao.FILA and "parou no meio" in t.erro


@pytest.mark.django_db
def test_apaga_so_as_terminadas_antigas():
    velha, nova, na_fila = enfileirar("teste_ok"), enfileirar("teste_ok"), enfileirar("teste_ok")
    Tarefa.objects.filter(pk=velha.pk).update(situacao=Situacao.FEITA, terminada_em=timezone.now() - timedelta(days=31))
    Tarefa.objects.filter(pk=nova.pk).update(situacao=Situacao.FALHOU, terminada_em=timezone.now() - timedelta(days=5))
    assert fila.apagar_antigas() == 1
    assert set(Tarefa.objects.values_list("pk", flat=True)) == {nova.pk, na_fila.pk}


def test_dois_trabalhadores_nao_pegam_a_mesma_tarefa(django_db_setup, django_db_blocker):
    """Com dados gravados de verdade: outra conexão segura a tarefa; esta conexão pula."""
    with django_db_blocker.unblock():
        t = enfileirar("teste_ok")
        config = connection.settings_dict
        try:
            with psycopg.connect(
                dbname=config["NAME"], user=config["USER"], password=config["PASSWORD"],
                host=config["HOST"], port=config["PORT"],
            ) as outro:
                with outro.transaction():
                    outro.execute("select id from tarefas_tarefa where id = %s for update", [t.pk])
                    assert pegar_proxima() is None  # travada pelo outro trabalhador: pula
            assert pegar_proxima().pk == t.pk      # liberada: agora pega
        finally:
            Tarefa.objects.filter(pk=t.pk).delete()


# Periódicas -------------------------------------------------------------------------

def quando(texto):
    return datetime.strptime(texto, "%d/%m/%Y %H:%M").replace(tzinfo=SP)


def test_ultimo_horario():
    assert periodicas.ultimo_horario(quando("21/11/2026 10:45"), None, 30) == quando("21/11/2026 10:30")
    assert periodicas.ultimo_horario(quando("21/11/2026 10:10"), None, 30) == quando("21/11/2026 09:30")
    assert periodicas.ultimo_horario(quando("21/11/2026 02:00"), 3, 15) == quando("20/11/2026 03:15")
    assert periodicas.ultimo_horario(quando("21/11/2026 03:15"), 3, 15) == quando("21/11/2026 03:15")


@pytest.mark.django_db
def test_periodica_roda_uma_vez_por_horario(monkeypatch):
    chamadas = []
    monkeypatch.setattr(periodicas, "_periodicas", [("teste_hora", None, 30, chamadas.append)])
    assert periodicas.rodar_periodicas(quando("21/11/2026 10:31")) == ["teste_hora"]
    assert periodicas.rodar_periodicas(quando("21/11/2026 10:59")) == []
    assert periodicas.rodar_periodicas(quando("21/11/2026 11:29")) == []
    assert periodicas.rodar_periodicas(quando("21/11/2026 11:30")) == ["teste_hora"]
    # Parado por 5 horas: roda uma vez só ao voltar.
    assert periodicas.rodar_periodicas(quando("21/11/2026 16:40")) == ["teste_hora"]
    assert periodicas.rodar_periodicas(quando("21/11/2026 16:41")) == []
    assert len(chamadas) == 3
    assert Periodica.objects.get(nome="teste_hora").ultima_vez == quando("21/11/2026 16:30")


@pytest.mark.django_db
def test_periodica_com_erro_nao_impede_as_outras_e_tenta_de_novo(monkeypatch):
    chamadas = []

    def quebra(agora):
        raise RuntimeError("x")

    monkeypatch.setattr(periodicas, "_periodicas", [("quebra", None, 30, quebra), ("boa", None, 30, chamadas.append)])
    assert periodicas.rodar_periodicas(quando("21/11/2026 10:31")) == ["boa"]
    assert not Periodica.objects.filter(nome="quebra", ultima_vez__isnull=False).exists()


def test_periodicas_registradas():
    assert {"limpar_tarefas", "coletar_clientes"} <= set(periodicas.nomes())
