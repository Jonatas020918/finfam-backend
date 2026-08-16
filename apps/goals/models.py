from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from apps.common.models import TenantScopedModel


class Goal(TenantScopedModel):
    """Meta financeira com progresso visual (seção 3.5)."""

    household = models.ForeignKey(
        "households.Household", on_delete=models.CASCADE, related_name="metas"
    )
    membro = models.ForeignKey(
        "households.Member",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="metas",
        help_text="Nulo = meta familiar/compartilhada.",
    )
    objetivo = models.ForeignKey(
        "households.LifeGoal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="metas",
        help_text="Vínculo opcional com um objetivo de vida do onboarding.",
    )
    descricao = models.CharField(max_length=180)
    valor_alvo = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    valor_atual = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    data_alvo = models.DateField(null=True, blank=True)
    concluida = models.BooleanField(default=False)

    class Meta:
        verbose_name = "meta"
        verbose_name_plural = "metas"
        ordering = ["data_alvo", "descricao"]

    def __str__(self) -> str:
        return self.descricao

    @property
    def progresso_percentual(self) -> Decimal:
        """Progresso de 0 a 100, limitado a 100 mesmo se o alvo for superado."""
        if not self.valor_alvo:
            return Decimal("0")
        pct = (Decimal(self.valor_atual) / Decimal(self.valor_alvo)) * 100
        return min(pct, Decimal("100")).quantize(Decimal("0.01"))

    @property
    def compartilhada(self) -> bool:
        return self.membro_id is None
