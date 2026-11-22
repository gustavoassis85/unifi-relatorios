"""Tarefas do trabalhador para e-mail: o envio de teste do SMTP."""
import logging

from django.contrib.auth import get_user_model
from django.utils import timezone

from organizacoes.isolamento import contexto
from tarefas.fila import ErroDefinitivo, enfileirar, tarefa

from .correio import ErroEnvio, mandar, mensagem_de_teste
from .models import ConfigSmtp

log = logging.getLogger("envios")

TESTE = "testar_smtp"


def enfileirar_teste(config, usuario):
    return enfileirar(TESTE, organizacao_id=config.organizacao_id, exclusiva=f"{TESTE}:{config.organizacao_id}",
                      pedida_por_id=usuario.pk, max_tentativas=1, usuario_id=usuario.pk)


@tarefa(TESTE)
def testar_smtp(tarefa_):
    org_id = tarefa_.organizacao_id
    usuario = get_user_model().objects.filter(pk=tarefa_.parametros.get("usuario_id")).first()
    with contexto(organizacao_id=org_id):
        config = ConfigSmtp.objects.first()
        if config is None:
            raise ErroDefinitivo("O servidor de e-mail não está mais configurado.")
        if usuario is None:
            resultado, ok = "O usuário que pediu o teste não existe mais.", False
        else:
            try:
                mandar(config, mensagem_de_teste(usuario.email))
                resultado, ok = f"E-mail de teste enviado para {usuario.email}.", True
            except ErroEnvio as erro:
                resultado, ok = str(erro), False
        config.testado_em = timezone.now()
        config.teste_ok = ok
        config.teste_resultado = resultado[:300]
        config.save(update_fields=["testado_em", "teste_ok", "teste_resultado"])
    log.info("Teste de SMTP da organização %s: %s", org_id, "ok" if ok else "falhou")
