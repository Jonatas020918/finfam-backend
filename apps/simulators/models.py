from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from apps.common.models import TenantScopedModel


class SimulationRun(TenantScopedModel):
    """Histórico de simulações PJ x CLT x Autônomo (seção 3.3).

    Guardamos entrada e saída para que o resultado exibido ao cliente seja
    reproduzível e possa ser anexado ao relatório em PDF, mesmo que as regras
    de cálculo mudem em versões futuras.
    """

    household = models.ForeignKey(
        "households.Household", on_delete=models.CASCADE, related_name="simulacoes"
    )
    membro = models.ForeignKey(
        "households.Member",
        on_delete=models.CASCADE,
        related_name="simulacoes",
        null=True,
        blank=True,
    )
    # DjangoJSONEncoder para persistir os Decimal do motor de cálculo sem perda.
    entrada = models.JSONField(encoder=DjangoJSONEncoder)
    resultado = models.JSONField(encoder=DjangoJSONEncoder)
    versao_regras = models.CharField(max_length=20)

    class Meta:
        verbose_name = "simulação"
        verbose_name_plural = "simulações"
        ordering = ["-criado_em"]

    def __str__(self) -> str:
        return f"Simulação {self.criado_em:%d/%m/%Y}"
