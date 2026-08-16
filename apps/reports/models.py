from django.db import models

from apps.common.models import TenantScopedModel


class TipoRelatorio(models.TextChoices):
    RETRATO_FINANCEIRO = "retrato_financeiro", "Retrato financeiro (self-service)"
    REVISAO_CONSULTORIA = "revisao_consultoria", "Revisão de consultoria (Fase 2)"


class ClientReport(TenantScopedModel):
    """PDF gerado para o cliente (seção 3.9)."""

    household = models.ForeignKey(
        "households.Household", on_delete=models.CASCADE, related_name="relatorios"
    )
    tipo = models.CharField(
        max_length=25, choices=TipoRelatorio.choices, default=TipoRelatorio.RETRATO_FINANCEIRO
    )
    referencia_ano = models.PositiveIntegerField()
    referencia_mes = models.PositiveSmallIntegerField()
    # Snapshot dos números no momento da geração — o PDF não pode mudar depois.
    snapshot = models.JSONField(default=dict)
    arquivo = models.FileField(upload_to="relatorios/%Y/%m/", blank=True)
    gerado_por = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        verbose_name = "relatório do cliente"
        verbose_name_plural = "relatórios do cliente"
        ordering = ["-criado_em"]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} {self.referencia_mes:02d}/{self.referencia_ano}"
