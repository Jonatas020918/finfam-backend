from django.db import models

from apps.common.models import TimeStampedModel


class TenantTipo(models.TextChoices):
    PLATAFORMA = "plataforma", "Plataforma (clientes self-service)"
    CONSULTOR = "consultor", "Workspace de consultor"


class Tenant(TimeStampedModel):
    """Workspace isolado.

    Existe exatamente um tenant do tipo `plataforma`, que abriga todos os
    clientes self-service (Fase 1). Cada consultor (Fases 2 e 3) recebe um
    tenant próprio — a estrutura já nasce pronta para isso.
    """

    nome = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120, unique=True)
    tipo = models.CharField(
        max_length=20, choices=TenantTipo.choices, default=TenantTipo.CONSULTOR
    )
    # Fase 3 — white-label leve
    marca_logo_url = models.URLField(blank=True)
    marca_cor_primaria = models.CharField(max_length=7, blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "tenant"
        verbose_name_plural = "tenants"

    def __str__(self) -> str:
        return self.nome

    @classmethod
    def plataforma(cls) -> "Tenant":
        """Tenant padrão dos clientes self-service (criado por data migration)."""
        return cls.objects.get(tipo=TenantTipo.PLATAFORMA)
