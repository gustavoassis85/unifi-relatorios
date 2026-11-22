"""Envio dos relatórios por e-mail: o SMTP de cada organização e os agendamentos.

A senha do SMTP fica cifrada (cofre/cifra.py); depois de salva, só os 4 últimos
caracteres aparecem na tela, e só para o admin.
"""
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from cofre.cifra import cifrar, decifrar, ultimos4
from coletas.models import DoCliente
from organizacoes.isolamento import ModeloDaOrganizacao

PORTAS = [25, 465, 587, 2525]


class Seguranca(models.TextChoices):
    STARTTLS = "starttls", "STARTTLS (normalmente porta 587)"
    SSL = "ssl", "SSL/TLS direto (normalmente porta 465)"


class ConfigSmtp(ModeloDaOrganizacao):
    """Servidor de e-mail da organização. Um por organização."""

    CAMPOS_CIFRADOS = ["senha_cifrada"]

    ativo = models.BooleanField("enviar e-mails por este servidor", default=True)
    servidor = models.CharField("servidor", max_length=253, help_text="Exemplo: smtp.gmail.com")
    porta = models.PositiveIntegerField("porta", choices=[(p, str(p)) for p in PORTAS], default=587)
    seguranca = models.CharField("segurança", max_length=10, choices=Seguranca.choices,
                                 default=Seguranca.STARTTLS)
    usuario = models.CharField("usuário", max_length=254, blank=True,
                               help_text="Em branco se o servidor não pede login.")
    senha_cifrada = models.TextField("senha cifrada", blank=True, editable=False)
    final = models.CharField("últimos 4 caracteres", max_length=4, blank=True, editable=False)
    remetente = models.EmailField("e-mail do remetente",
                                  help_text="O nome que aparece é o nome da empresa na Marca.")
    atualizado_em = models.DateTimeField("atualizado em", default=timezone.now, editable=False)
    teste_pedido_em = models.DateTimeField("teste pedido em", null=True, blank=True, editable=False)
    testado_em = models.DateTimeField("último teste em", null=True, blank=True, editable=False)
    teste_ok = models.BooleanField("último teste funcionou", null=True, editable=False)
    teste_resultado = models.CharField("resultado do último teste", max_length=300, blank=True, editable=False)

    class Meta:
        verbose_name = "servidor de e-mail"
        verbose_name_plural = "servidores de e-mail"
        constraints = [models.UniqueConstraint(fields=["organizacao"], name="smtp_unico_na_organizacao")]

    def __str__(self):
        return f"{self.servidor}:{self.porta}"

    def definir_senha(self, senha):
        """Guarda a senha cifrada (vazia apaga). Não grava no banco: chame save() depois."""
        self.senha_cifrada = cifrar(senha) if senha else ""
        self.final = ultimos4(senha) if senha else ""

    def abrir_senha(self):
        """A senha em texto, só para conectar. Nunca mostrar nem registrar."""
        return decifrar(self.senha_cifrada) if self.senha_cifrada else ""

    @property
    def teste_pendente(self):
        # Pedido há mais de 10 min sem resposta: o trabalhador está desligado; a tela para de esperar.
        if not self.teste_pedido_em or self.teste_pedido_em < timezone.now() - timedelta(minutes=10):
            return False
        return self.testado_em is None or self.testado_em < self.teste_pedido_em


class Frequencia(models.TextChoices):
    MENSAL = "mensal", "Mensal (cobre o mês anterior)"
    SEMANAL = "semanal", "Semanal (cobre os últimos 7 dias)"


DIAS_DA_SEMANA = [(0, "segunda-feira"), (1, "terça-feira"), (2, "quarta-feira"), (3, "quinta-feira"),
                  (4, "sexta-feira"), (5, "sábado"), (6, "domingo")]
MAX_AGENDAMENTOS_POR_CLIENTE = 5
MAX_DESTINATARIOS = 10


class Agendamento(DoCliente):
    """Relatório automático de um cliente: quando sai e para quem vai."""

    frequencia = models.CharField("frequência", max_length=10, choices=Frequencia.choices,
                                  default=Frequencia.MENSAL)
    dia_do_mes = models.PositiveSmallIntegerField("dia do mês", null=True, blank=True,
                                                  choices=[(d, str(d)) for d in range(1, 29)])
    dia_da_semana = models.PositiveSmallIntegerField("dia da semana", null=True, blank=True,
                                                     choices=DIAS_DA_SEMANA)
    hora = models.PositiveSmallIntegerField("hora", default=8, choices=[(h, f"{h:02d}:00") for h in range(24)])
    destinatarios = models.JSONField("destinatários", default=list, blank=True)
    ativo = models.BooleanField("ativo", default=True)
    proxima_execucao = models.DateTimeField("próxima execução", null=True, blank=True)
    ultima_execucao = models.DateTimeField("última execução", null=True, blank=True, editable=False)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+", verbose_name="criado por", editable=False)
    criado_em = models.DateTimeField("criado em", default=timezone.now, editable=False)

    class Meta:
        verbose_name = "agendamento"
        verbose_name_plural = "agendamentos"
        ordering = ["criado_em"]
        indexes = [models.Index(fields=["ativo", "proxima_execucao"])]
        constraints = [
            models.CheckConstraint(
                name="agendamento_dia_conforme_frequencia",
                condition=(models.Q(frequencia="mensal", dia_do_mes__gte=1, dia_do_mes__lte=28)
                           | models.Q(frequencia="semanal", dia_da_semana__gte=0, dia_da_semana__lte=6)),
            ),
            models.CheckConstraint(name="agendamento_hora_valida", condition=models.Q(hora__lte=23)),
        ]

    def __str__(self):
        return self.descricao

    @property
    def descricao(self):
        if self.frequencia == Frequencia.MENSAL:
            return f"Todo dia {self.dia_do_mes}, às {self.hora:02d}:00"
        artigo = "Todo" if self.dia_da_semana >= 5 else "Toda"   # sábado e domingo
        return f"{artigo} {dict(DIAS_DA_SEMANA)[self.dia_da_semana]}, às {self.hora:02d}:00"


class SituacaoEnvio(models.TextChoices):
    PENDENTE = "pendente", "Enviando"
    ENVIADO = "enviado", "Enviado"
    NAO_ENVIADO = "nao_enviado", "Não enviado"
    FALHOU = "falhou", "Envio falhou"


class Envio(DoCliente):
    """Um envio de relatório por e-mail. Apagado junto com o relatório (13 meses)."""

    relatorio = models.ForeignKey("relatorios.Relatorio", on_delete=models.CASCADE, related_name="+",
                                  verbose_name="relatório")
    destinatarios = models.JSONField("destinatários", default=list)
    situacao = models.CharField("situação", max_length=12, choices=SituacaoEnvio.choices,
                                default=SituacaoEnvio.PENDENTE)
    motivo = models.CharField("motivo", max_length=300, blank=True)
    tentativas = models.PositiveSmallIntegerField("tentativas", default=0)
    pedido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+", verbose_name="reenviado por")
    criado_em = models.DateTimeField("criado em", default=timezone.now)
    enviado_em = models.DateTimeField("enviado em", null=True, blank=True)

    class Meta:
        verbose_name = "envio"
        verbose_name_plural = "envios"
        ordering = ["-criado_em"]
        indexes = [models.Index(fields=["relatorio", "-criado_em"])]
