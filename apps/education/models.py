from django.db import models

from apps.common.models import TimeStampedModel

DISCLAIMER_PADRAO = (
    "Este conteúdo tem caráter exclusivamente educacional e informativo. Não "
    "constitui recomendação de investimento, oferta ou análise personalizada. "
    "Decisões de investimento devem ser tomadas com apoio de profissional "
    "certificado pela CVM, considerando o perfil individual do investidor."
)


class StatusRelatorio(models.TextChoices):
    RASCUNHO = "rascunho", "Rascunho (gerado por IA)"
    EM_REVISAO = "em_revisao", "Em revisão humana"
    PUBLICADO = "publicado", "Publicado"


class EducationalReport(TimeStampedModel):
    """Relatório educacional mensal (seção 3.6).

    Os indicadores vêm sempre da API oficial do Banco Central; a IA apenas
    redige o texto a partir deles. Revisão humana é obrigatória antes de
    publicar — por isso o status inicia em `rascunho`.
    """

    # Nulo = relatório global da plataforma (padrão na Fase 1).
    tenant = models.ForeignKey(
        "tenancy.Tenant",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="relatorios_educacionais",
    )
    ano = models.PositiveIntegerField()
    mes = models.PositiveSmallIntegerField()
    titulo = models.CharField(max_length=180)

    # Dados-fonte oficiais (nunca estimados pela IA)
    selic_meta_percentual = models.DecimalField(max_digits=6, decimal_places=2, null=True)
    selic_variacao_mes = models.DecimalField(max_digits=6, decimal_places=2, null=True)
    ipca_mes_percentual = models.DecimalField(max_digits=6, decimal_places=2, null=True)
    ipca_12m_percentual = models.DecimalField(max_digits=6, decimal_places=2, null=True)
    fonte_dados = models.CharField(max_length=120, default="Banco Central do Brasil (SGS)")

    # Conteúdo em blocos: [{"titulo": ..., "corpo": ...}, ...]
    secoes = models.JSONField(default=list)
    glossario = models.JSONField(default=list)
    disclaimer = models.TextField(default=DISCLAIMER_PADRAO)

    status = models.CharField(
        max_length=20, choices=StatusRelatorio.choices, default=StatusRelatorio.RASCUNHO
    )
    revisado_por = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    publicado_em = models.DateTimeField(null=True, blank=True)
    modelo_ia = models.CharField(max_length=80, blank=True)

    class Meta:
        verbose_name = "relatório educacional"
        verbose_name_plural = "relatórios educacionais"
        ordering = ["-ano", "-mes"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "ano", "mes"], name="relatorio_unico_por_mes_tenant"
            )
        ]

    def __str__(self) -> str:
        return f"{self.titulo} ({self.mes:02d}/{self.ano})"
