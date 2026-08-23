from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.common.models import TenantScopedModel
from apps.households.models import RegimeTributario, TipoRenda


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


class RecurringExpense(TenantScopedModel):
    """Despesa que se repete todo mês (aluguel, escola, parcela, plano de saúde).

    É um **modelo**, não um lançamento: descreve o que deve acontecer todo mês.
    Quando a competência é aberta, vira um `CashFlowEntry` de verdade — e a
    partir daí o usuário pode ajustar o valor daquele mês específico sem mexer
    no cadastro.

    Existe porque redigitar "Aluguel · R$ 8.000" doze vezes por ano é trabalho
    que o software deveria fazer, e porque esquecer de redigitar fazia o fluxo
    de caixa parecer melhor do que é.
    """

    household = models.ForeignKey(
        "households.Household", on_delete=models.CASCADE, related_name="despesas_recorrentes"
    )
    membro = models.ForeignKey(
        "households.Member",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="despesas_recorrentes",
        help_text="Nulo = despesa compartilhada pela família.",
    )
    descricao = models.CharField(max_length=180)
    categoria = models.CharField(
        max_length=25,
        choices=[
            ("despesa_fixa", "Despesa fixa"),
            ("despesa_variavel", "Despesa variável"),
            ("investimento", "Investimento/aporte"),
            ("divida", "Pagamento de dívida"),
            ("imposto", "Impostos"),
        ],
        default="despesa_fixa",
    )
    valor_previsto = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(0)]
    )
    dia_vencimento = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
    )

    # Vigência: uma parcela que acabou para de aparecer sozinha, em vez de
    # inflar as despesas para sempre.
    vigencia_inicio = models.DateField()
    vigencia_fim = models.DateField(null=True, blank=True)
    ativa = models.BooleanField(default=True)

    divida = models.ForeignKey(
        "households.Debt",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="despesas_recorrentes",
        help_text="Vincula a parcela ao financiamento correspondente.",
    )

    class Meta:
        verbose_name = "despesa recorrente"
        verbose_name_plural = "despesas recorrentes"
        ordering = ["descricao"]

    def __str__(self) -> str:
        return f"{self.descricao} (todo mês)"

    def vigente_em(self, ano: int, mes: int) -> bool:
        """A recorrência vale para esta competência?"""
        if not self.ativa:
            return False
        inicio = (self.vigencia_inicio.year, self.vigencia_inicio.month)
        if (ano, mes) < inicio:
            return False
        if self.vigencia_fim:
            fim = (self.vigencia_fim.year, self.vigencia_fim.month)
            if (ano, mes) > fim:
                return False
        return True


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

    # --- Classificação da receita (só faz sentido quando tipo=receita) -------
    # Vincular o lançamento à fonte declarada no onboarding é o caminho
    # preferencial: o regime, o tipo e o membro vêm dela, sem redigitação e sem
    # risco de divergir. Os campos abaixo ficam preenchidos mesmo assim, para
    # que relatórios e simulações não precisem de JOIN — e para que uma receita
    # avulsa (sem fonte cadastrada) também possa ser classificada.
    fonte_renda = models.ForeignKey(
        "households.IncomeSource",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lancamentos",
    )
    regime = models.CharField(
        max_length=20,
        choices=RegimeTributario.choices,
        blank=True,
        help_text="Regime tributário da receita. Alimenta o simulador PJ x CLT.",
    )
    tipo_renda = models.CharField(
        max_length=20,
        choices=TipoRenda.choices,
        blank=True,
        help_text="Serviço avulso, salário CLT, PJ/negócio próprio...",
    )
    # O que efetivamente entrou ou saiu da conta. No CLT, é o líquido: o fluxo
    # de caixa registra dinheiro que existe, não o que o contrato prometia.
    valor_realizado = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    # Preenchido apenas quando houve retenção na fonte, para a tela conseguir
    # mostrar de onde veio o desconto. Sem isto, o cliente vê R$ 18 mil onde
    # informou R$ 24 mil e conclui que a plataforma errou a conta.
    valor_bruto = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Valor antes da retenção na fonte, quando houver.",
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

    # Preenchido quando o lançamento nasceu de uma recorrência. Serve para a
    # materialização ser idempotente e para a tela mostrar o que é automático.
    despesa_recorrente = models.ForeignKey(
        RecurringExpense,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lancamentos",
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

    @property
    def receita_classificada(self) -> bool:
        """Receita que o simulador consegue usar (tem regime definido)."""
        return self.tipo == TipoLancamento.RECEITA and bool(self.regime)

    @property
    def recorrente(self) -> bool:
        """Veio de um cadastro fixo, em vez de ter sido digitado neste mês."""
        if self.despesa_recorrente_id:
            return True
        return bool(self.fonte_renda_id and self.fonte_renda.fixa)
