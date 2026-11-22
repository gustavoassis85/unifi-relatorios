from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


class UsuarioManager(BaseUserManager):
    use_in_migrations = True

    def normalizar_email(self, email):
        return (email or "").strip().lower()

    def get_by_natural_key(self, email):
        return self.get(email__iexact=self.normalizar_email(email))

    def _criar(self, email, password, **campos):
        email = self.normalizar_email(email)
        if not email:
            raise ValueError("O e-mail é obrigatório.")
        usuario = self.model(email=email, **campos)
        usuario.set_password(password)
        usuario.save(using=self._db)
        return usuario

    def create_user(self, email, password=None, **campos):
        campos.setdefault("is_staff", False)
        campos.setdefault("is_superuser", False)
        return self._criar(email, password, **campos)

    def create_superuser(self, email, password=None, **campos):
        campos["is_staff"] = True
        campos["is_superuser"] = True
        return self._criar(email, password, **campos)


class Usuario(AbstractBaseUser, PermissionsMixin):
    """Usuário com login por e-mail. O dono da plataforma é o superusuário do Django."""

    email = models.EmailField("e-mail", unique=True)
    nome = models.CharField("nome", max_length=150, blank=True)
    is_active = models.BooleanField("ativo", default=True)
    is_staff = models.BooleanField("acessa o admin", default=False)
    criado_em = models.DateTimeField("criado em", default=timezone.now)

    objects = UsuarioManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"
        constraints = [
            # Fulano@X.com e fulano@x.com são o mesmo e-mail.
            models.UniqueConstraint(Lower("email"), name="usuario_email_unico_sem_maiusculas"),
        ]

    def clean(self):
        super().clean()
        self.email = type(self).objects.normalizar_email(self.email)

    def __str__(self):
        return self.email
