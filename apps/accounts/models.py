from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models

from apps.common.models import TimeStampedModel


class Papel(models.TextChoices):
    CLIENTE = "cliente", "Cliente (titular ou cônjuge)"
    CONSULTOR = "consultor", "Consultor"
    ADMIN = "admin", "Administrador da plataforma"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("E-mail é obrigatório")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("papel", Papel.ADMIN)
        if extra.get("is_staff") is not True or extra.get("is_superuser") is not True:
            raise ValueError("Superusuário precisa de is_staff e is_superuser")
        return self._create_user(email, password, **extra)


class User(AbstractUser, TimeStampedModel):
    """Usuário autenticável. Login por e-mail; `username` é removido."""

    username = None
    first_name = None
    last_name = None

    email = models.EmailField(unique=True)
    nome_completo = models.CharField(max_length=180)
    telefone = models.CharField(max_length=20, blank=True)
    papel = models.CharField(max_length=20, choices=Papel.choices, default=Papel.CLIENTE)
    tenant = models.ForeignKey(
        "tenancy.Tenant",
        on_delete=models.PROTECT,
        related_name="usuarios",
        null=True,
        blank=True,
    )
    aceite_disclaimer_educacional_em = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["nome_completo"]

    objects = UserManager()

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"

    def __str__(self) -> str:
        return f"{self.nome_completo} <{self.email}>"

    @property
    def is_consultor(self) -> bool:
        return self.papel == Papel.CONSULTOR
