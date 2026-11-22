"""Eventos de auditoria. Só de acréscimo: o usuário da aplicação no banco pode
incluir e ler, mas não alterar nem apagar (ver config/banco.py)."""
from django.conf import settings
from django.db import models
from django.utils import timezone

from organizacoes.isolamento import ModeloDaOrganizacao


class Acao(models.TextChoices):
    LOGIN = "login", "Login"
    LOGIN_FALHOU = "login_falhou", "Falha de login"
    LOGOUT = "logout", "Logout"
    USUARIO_CRIADO = "usuario_criado", "Usuário criado"
    USUARIO_ALTERADO = "usuario_alterado", "Usuário alterado"
    CLIENTE_CRIADO = "cliente_criado", "Cliente criado"
    CLIENTE_ALTERADO = "cliente_alterado", "Cliente alterado"
    CLIENTE_APAGADO = "cliente_apagado", "Cliente apagado"
    CHAVE_CADASTRADA = "chave_cadastrada", "Chave da UniFi cadastrada"
    CHAVE_TROCADA = "chave_trocada", "Chave da UniFi trocada"
    CHAVE_APAGADA = "chave_apagada", "Chave da UniFi apagada"
    CONEXAO_TESTADA = "conexao_testada", "Conexão com a UniFi testada"
    CONSOLE_ACOMPANHADO = "console_acompanhado", "Console passou a ser acompanhado"
    CONSOLE_NAO_ACOMPANHADO = "console_nao_acompanhado", "Console deixou de ser acompanhado"
    COLETA_PEDIDA = "coleta_pedida", "Coleta pedida"
    MARCA_ALTERADA = "marca_alterada", "Marca alterada"
    RELATORIO_PEDIDO = "relatorio_pedido", "Relatório pedido"
    RELATORIO_BAIXADO = "relatorio_baixado", "PDF do relatório baixado"
    SMTP_ALTERADO = "smtp_alterado", "Servidor de e-mail alterado"
    SMTP_TESTADO = "smtp_testado", "Teste do servidor de e-mail pedido"
    AGENDAMENTO_CRIADO = "agendamento_criado", "Agendamento criado"
    AGENDAMENTO_ALTERADO = "agendamento_alterado", "Agendamento alterado"
    AGENDAMENTO_PAUSADO = "agendamento_pausado", "Agendamento pausado"
    AGENDAMENTO_RETOMADO = "agendamento_retomado", "Agendamento retomado"
    AGENDAMENTO_EXCLUIDO = "agendamento_excluido", "Agendamento excluído"
    RELATORIO_REENVIADO = "relatorio_reenviado", "Relatório reenviado por e-mail"
    ORGANIZACAO_CRIADA = "organizacao_criada", "Organização criada"
    ORGANIZACAO_ALTERADA = "organizacao_alterada", "Organização alterada"


class CamposDoEvento(models.Model):
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="usuário",
    )
    acao = models.CharField("ação", max_length=40, choices=Acao.choices)
    ip = models.GenericIPAddressField("IP", null=True, blank=True)
    detalhes = models.JSONField("detalhes", default=dict, blank=True)
    criado_em = models.DateTimeField("data", default=timezone.now)

    class Meta:
        abstract = True
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.criado_em:%d/%m/%Y %H:%M} {self.get_acao_display()}"


class EventoOrganizacao(CamposDoEvento, ModeloDaOrganizacao):
    """Evento de uma organização. Protegido pela RLS como qualquer dado de MSP."""

    class Meta(CamposDoEvento.Meta):
        verbose_name = "evento da organização"
        verbose_name_plural = "eventos da organização"
        indexes = [models.Index(fields=["organizacao", "-criado_em"])]


class EventoPlataforma(CamposDoEvento):
    """Evento sem organização: ações do dono da plataforma e falhas de login
    de e-mails que não pertencem a nenhuma organização."""

    class Meta(CamposDoEvento.Meta):
        verbose_name = "evento da plataforma"
        verbose_name_plural = "eventos da plataforma"
        indexes = [models.Index(fields=["-criado_em"])]
