from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.common.models import TenantScopedModel


class TipoLancamento(models.TextChoices):
    RECEITA = "receita", "Receita"
    DESPESA = "despesa", "Despesa"


class CategoriaLancamento(models.TextChoices):
    # Receitas
    RENDA_TRABALHO = "renda_trabalho", "Renda do trabalho"
    RENDA_INVESTIMENTO = "renda_investimento", "Renda de investimentos"
    OUTRA_RECEITA = "outra_receita", "Outra receita"
    # Despesas (seção 3.2)
    DESPESA_FIXA = "despesa_fixa", "Despesa fixa"
    DESPESA_VARIAVEL = "despesa_variavel", "Despesa variável"
    INVESTIMENTO = "investimento", "Investimento/aporte"
    DIVIDA = "divida", "Pagamento de dívida"
    IMPOSTO = "imposto", "Impostos"


class CashFlowEntry(TenantScopedModel):
    """Lançamento manual de receita ou despesa em um mês de competência.

    Sem integração bancária — todo lançamento é informado pelo usuário.
    """

    household = models.ForeignKey(
        "households.Household", on_delete=models.CASCADE, related_name="lancamentos"
    )
    membro = models.ForeignKey(
        "households.Member",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lancamentos",
        help_text="Nulo = lançamento compartilhado pela família.",
    )
    tipo = models.CharField(max_length=10, choices=TipoLancamento.choices)
    categoria = models.CharField(max_length=25, choices=CategoriaLancamento.choices)
    descricao = models.CharField(max_length=180)
    valor_realizado = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    valor_orcado = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Comparativo orçado x realizado (seção 3.2).",
    )
    ano = models.PositiveIntegerField(validators=[MinValueValidator(2000)])
    mes = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(12)]
    )

    class Meta:
        verbose_name = "lançamento de fluxo de caixa"
        verbose_name_plural = "lançamentos de fluxo de caixa"
        indexes = [models.Index(fields=["household", "ano", "mes"])]
        ordering = ["-ano", "-mes", "descricao"]

    def __str__(self) -> str:
        return f"{self.descricao} {self.mes:02d}/{self.ano}"

    @property
    def compartilhado(self) -> bool:
        return self.membro_id is None
