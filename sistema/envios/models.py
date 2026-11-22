"""Envio dos relatórios por e-mail: o SMTP de cada organização.

A senha do SMTP fica cifrada (cofre/cifra.py); depois de salva, só os 4 últimos
caracteres aparecem na tela, e só para o admin.
"""
from django.db import models
from django.utils import timezone

from cofre.cifra import cifrar, decifrar, ultimos4
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
        return bool(self.teste_pedido_em and (self.testado_em is None or self.testado_em < self.teste_pedido_em))
