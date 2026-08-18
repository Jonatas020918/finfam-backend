from django.db import models

from apps.common.models import TimeStampedModel

DISCLAIMER_PADRAO = (
    "Este conteúdo tem caráter exclusivamente educacional e informativo. Não "
    "constitui recomendação de investimento, oferta ou análise personalizada. "
    "Decisões de investimento devem ser tomadas com apoio de profissional "
    "certificado pela CVM, considerando o perfil individual do investidor."
)


class IndicadorMensal(TimeStampedModel):
    """Indicadores oficiais do Banco Central, por competência.

    Ficam separados de `EducationalReport` de propósito. O relatório é texto
    escrito por IA e precisa de revisão humana antes de ir ao ar (seção 3.6);
    Selic e IPCA são dado público e oficial, e travá-los atrás da mesma revisão
    faria a tela mostrar número velho — ou nenhum — enquanto ninguém revisasse.

    Atualizados por job diário: a meta Selic muda a cada reunião do Copom e o
    IPCA de um mês só sai por volta do dia 10 do mês seguinte, então a mesma
    competência é revisitada até ficar completa.
    """

    ano = models.PositiveIntegerField()
    mes = models.PositiveSmallIntegerField()

    selic_meta_percentual = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )
    selic_variacao_mes = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )
    ipca_mes_percentual = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )
    ipca_12m_percentual = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )

    fonte = models.CharField(max_length=120, default="Banco Central do Brasil (SGS)")
    sincronizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "indicador mensal"
        verbose_name_plural = "indicadores mensais"
        ordering = ["-ano", "-mes"]
        constraints = [
            models.UniqueConstraint(fields=["ano", "mes"], name="indicador_unico_por_mes")
        ]

    def __str__(self) -> str:
        return f"Indicadores {self.mes:02d}/{self.ano}"

    @property
    def completo(self) -> bool:
        return self.selic_meta_percentual is not None and self.ipca_mes_percentual is not None

    @classmethod
    def mais_recentes(cls) -> dict:
        """Último valor disponível de cada indicador, com sua competência.

        Cada série tem cadência própria: a Selic do mês corrente já existe, mas
        o IPCA ainda não. Devolver "o último mês completo" esconderia a Selic
        atual; por isso cada indicador carrega a referência dele.
        """

        def _ultimo(campo: str):
            registro = (
                cls.objects.exclude(**{f"{campo}__isnull": True})
                .order_by("-ano", "-mes")
                .first()
            )
            if registro is None:
                return None
            return {
                # String, como todo decimal desta API — evita que o cliente
                # receba número num campo e texto em outro do mesmo payload.
                "valor": str(getattr(registro, campo)),
                "ano": registro.ano,
                "mes": registro.mes,
                "referencia": f"{registro.mes:02d}/{registro.ano}",
            }

        return {
            "selic_meta": _ultimo("selic_meta_percentual"),
            "selic_variacao_mes": _ultimo("selic_variacao_mes"),
            "ipca_mes": _ultimo("ipca_mes_percentual"),
            "ipca_12m": _ultimo("ipca_12m_percentual"),
        }


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
