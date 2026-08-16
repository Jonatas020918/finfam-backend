from django.db import models

from apps.common.models import TimeStampedModel


class PlanoCodigo(models.TextChoices):
    SELF_SERVICE = "self_service", "Self-service"
    CONSULTORIA = "consultoria", "Consultoria (Fase 2)"
    LICENCA_CONSULTOR = "licenca_consultor", "Licença por consultor (Fase 3)"


class Plan(TimeStampedModel):
    codigo = models.CharField(max_length=25, choices=PlanoCodigo.choices, unique=True)
    nome = models.CharField(max_length=120)
    preco_mensal = models.DecimalField(max_digits=10, decimal_places=2)
    descricao = models.TextField(blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "plano"
        verbose_name_plural = "planos"

    def __str__(self) -> str:
        return self.nome


class StatusAssinatura(models.TextChoices):
    TRIAL = "trial", "Período de teste"
    ATIVA = "ativa", "Ativa"
    INADIMPLENTE = "inadimplente", "Inadimplente"
    CANCELADA = "cancelada", "Cancelada"


class Subscription(TimeStampedModel):
    """Assinatura do núcleo familiar (Fase 1) ou do consultor (Fase 3).

    O provedor de pagamento é tratado como detalhe externo: guardamos apenas o
    identificador da assinatura no gateway e reagimos a webhooks.
    """

    household = models.ForeignKey(
        "households.Household",
        on_delete=models.CASCADE,
        related_name="assinaturas",
        null=True,
        blank=True,
    )
    tenant = models.ForeignKey(
        "tenancy.Tenant",
        on_delete=models.CASCADE,
        related_name="assinaturas",
        null=True,
        blank=True,
    )
    plano = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="assinaturas")
    status = models.CharField(
        max_length=20, choices=StatusAssinatura.choices, default=StatusAssinatura.TRIAL
    )
    inicio = models.DateField()
    fim_periodo_atual = models.DateField(null=True, blank=True)
    gateway = models.CharField(max_length=40, blank=True)
    gateway_subscription_id = models.CharField(max_length=120, blank=True)

    class Meta:
        verbose_name = "assinatura"
        verbose_name_plural = "assinaturas"

    def __str__(self) -> str:
        alvo = self.household or self.tenant
        return f"{self.plano.nome} — {alvo}"

    @property
    def da_acesso(self) -> bool:
        return self.status in {StatusAssinatura.TRIAL, StatusAssinatura.ATIVA}
