from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from apps.common.models import TenantScopedModel


class ModoUso(models.TextChoices):
    SELF_SERVICE = "self_service", "Self-service"
    CONSULTORIA = "consultoria", "Consultoria"


class EstadoCivil(models.TextChoices):
    SOLTEIRO = "solteiro", "Solteiro(a)"
    CASADO = "casado", "Casado(a)"
    UNIAO_ESTAVEL = "uniao_estavel", "União estável"
    DIVORCIADO = "divorciado", "Divorciado(a)"
    VIUVO = "viuvo", "Viúvo(a)"


class RegimeBens(models.TextChoices):
    COMUNHAO_PARCIAL = "comunhao_parcial", "Comunhão parcial"
    COMUNHAO_UNIVERSAL = "comunhao_universal", "Comunhão universal"
    SEPARACAO_TOTAL = "separacao_total", "Separação total"
    PARTICIPACAO_FINAL = "participacao_final", "Participação final nos aquestos"
    NAO_APLICAVEL = "nao_aplicavel", "Não aplicável"


class Household(TenantScopedModel):
    """Núcleo familiar — a unidade de planejamento (o "cliente" da seção 5)."""

    nome = models.CharField(max_length=180, help_text="Ex.: Família Souza")
    modo = models.CharField(
        max_length=20, choices=ModoUso.choices, default=ModoUso.SELF_SERVICE
    )
    # Nulo no modo self-service; preenchido na Fase 2 (modo consultoria).
    consultor = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="carteira",
    )
    estado_civil = models.CharField(
        max_length=20, choices=EstadoCivil.choices, default=EstadoCivil.SOLTEIRO
    )
    regime_bens = models.CharField(
        max_length=25, choices=RegimeBens.choices, default=RegimeBens.NAO_APLICAVEL
    )
    onboarding_concluido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "núcleo familiar"
        verbose_name_plural = "núcleos familiares"
        indexes = [models.Index(fields=["tenant", "modo"])]

    def __str__(self) -> str:
        return self.nome

    @property
    def onboarding_concluido(self) -> bool:
        return self.onboarding_concluido_em is not None


class TipoMembro(models.TextChoices):
    TITULAR = "titular", "Titular"
    CONJUGE = "conjuge", "Cônjuge/companheiro(a)"
    DEPENDENTE = "dependente", "Dependente"


class Member(TenantScopedModel):
    """Membro do núcleo familiar (seção 2.5).

    Titular e cônjuge podem gerar renda; dependentes não têm renda nem login.
    """

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="membros"
    )
    tipo = models.CharField(max_length=20, choices=TipoMembro.choices)
    nome = models.CharField(max_length=180)
    data_nascimento = models.DateField(null=True, blank=True)
    profissao = models.CharField(max_length=120, blank=True)
    # Cônjuge pode ter login próprio (decisão do titular, seção 2.5).
    usuario = models.OneToOneField(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="membro",
    )
    # Dependentes: evento futuro relevante (ex.: previsão de faculdade)
    evento_futuro = models.CharField(max_length=180, blank=True)
    evento_futuro_ano = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "membro"
        verbose_name_plural = "membros"
        ordering = ["tipo", "nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["household"],
                condition=models.Q(tipo="titular"),
                name="unico_titular_por_household",
            )
        ]

    def __str__(self) -> str:
        return f"{self.nome} ({self.get_tipo_display()})"

    @property
    def pode_gerar_renda(self) -> bool:
        return self.tipo in {TipoMembro.TITULAR, TipoMembro.CONJUGE}


class RegimeTributario(models.TextChoices):
    CLT = "clt", "CLT"
    PJ = "pj", "PJ (Simples Nacional)"
    AUTONOMO = "autonomo", "Autônomo (RPA/Carnê-Leão)"


class TipoRenda(models.TextChoices):
    PLANTAO = "plantao", "Plantão"
    CLT_HOSPITALAR = "clt_hospitalar", "CLT hospitalar"
    PJ_CONSULTORIO = "pj_consultorio", "PJ / consultório"
    ALUGUEL = "aluguel", "Aluguel"
    OUTRA = "outra", "Outra"


class ModoLancamento(models.TextChoices):
    FIXA = "fixa", "Fixa (mesmo valor todo mês)"
    VARIAVEL = "variavel", "Variável (lançada mês a mês)"


class IncomeSource(TenantScopedModel):
    """Fonte de renda, sempre vinculada ao membro que a gera (seção 3.1).

    Renda de plantão e de consultório oscila bastante de um mês para o outro.
    Por isso a fonte tem dois modos:

    - `fixa`: o valor se repete todo mês (salário CLT, aluguel recebido). A
      plataforma materializa o lançamento sozinha quando a competência é aberta.
    - `variavel`: o valor muda a cada mês (plantão, consultório) e é lançado
      pelo cliente na aba de variáveis.

    Nos dois casos o dinheiro vira `CashFlowEntry`. É isso que mantém uma única
    fonte de verdade: o fluxo de caixa não soma "média cadastrada" com
    "lançamento real" — ele lê apenas lançamentos.
    """

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="fontes_renda"
    )
    membro = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="fontes_renda"
    )
    descricao = models.CharField(max_length=180)
    tipo = models.CharField(max_length=20, choices=TipoRenda.choices)
    regime = models.CharField(max_length=20, choices=RegimeTributario.choices)
    valor_medio_mensal = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(0)]
    )
    variabilidade_percentual = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Oscilação esperada em torno do valor médio, em %.",
    )
    modo_lancamento = models.CharField(
        max_length=10, choices=ModoLancamento.choices, default=ModoLancamento.FIXA
    )
    ativa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "fonte de renda"
        verbose_name_plural = "fontes de renda"

    def __str__(self) -> str:
        return f"{self.descricao} — {self.membro.nome}"

    @property
    def detalhada(self) -> bool:
        """Renda variável: exige lançamento mês a mês."""
        return self.modo_lancamento == ModoLancamento.VARIAVEL

    @property
    def fixa(self) -> bool:
        return self.modo_lancamento == ModoLancamento.FIXA

    def media_realizada(self, meses: int = 6) -> Decimal | None:
        """Média do que foi efetivamente lançado nas últimas competências.

        Só faz sentido no modo mensal; devolve None quando não há lançamentos,
        para o chamador distinguir "média zero" de "sem dado".
        """
        from django.db.models import Avg

        valores = self.lancamentos.order_by("-ano", "-mes")[:meses]
        if not valores:
            return None
        media = self.lancamentos.filter(
            pk__in=[lancamento.pk for lancamento in valores]
        ).aggregate(media=Avg("valor_realizado"))["media"]
        return Decimal(media).quantize(Decimal("0.01")) if media is not None else None


class Titularidade(models.TextChoices):
    TITULAR = "titular", "Titular"
    CONJUGE = "conjuge", "Cônjuge"
    CONJUNTO = "conjunto", "Conjunto/comunhão"


class TipoPatrimonio(models.TextChoices):
    IMOVEL = "imovel", "Imóvel"
    VEICULO = "veiculo", "Veículo"
    APLICACAO = "aplicacao", "Aplicação financeira"
    PARTICIPACAO = "participacao", "Participação societária"
    PREVIDENCIA = "previdencia", "Previdência"
    OUTRO = "outro", "Outro"


class Asset(TenantScopedModel):
    """Patrimônio (seção 3.1/3.4). Sem integração bancária: valor informado."""

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="patrimonios"
    )
    membro = models.ForeignKey(
        Member,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="patrimonios",
        help_text="Preenchido quando o bem é individual.",
    )
    tipo = models.CharField(max_length=20, choices=TipoPatrimonio.choices)
    descricao = models.CharField(max_length=180)
    valor_atual = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(0)]
    )
    titularidade = models.CharField(
        max_length=20, choices=Titularidade.choices, default=Titularidade.TITULAR
    )
    # Planejamento sucessório (seção 3.4)
    detentor_juridico = models.CharField(
        max_length=120, blank=True, help_text="Pessoa física, PJ, holding..."
    )

    class Meta:
        verbose_name = "patrimônio"
        verbose_name_plural = "patrimônios"

    def __str__(self) -> str:
        return self.descricao


class TipoDivida(models.TextChoices):
    FINANCIAMENTO_IMOVEL = "financiamento_imovel", "Financiamento de imóvel"
    FINANCIAMENTO_VEICULO = "financiamento_veiculo", "Financiamento de veículo"
    CONSULTORIO = "consultorio", "Consultório"
    EQUIPAMENTO = "equipamento", "Equipamento"
    RESIDENCIA_MEDICA = "residencia_medica", "Financiamento de residência médica"
    CARTAO = "cartao", "Cartão de crédito"
    OUTRA = "outra", "Outra"


class SistemaAmortizacao(models.TextChoices):
    PRICE = "price", "Price (parcela fixa)"
    SAC = "sac", "SAC (parcela decrescente)"


class Debt(TenantScopedModel):
    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="dividas"
    )
    membro = models.ForeignKey(
        Member, on_delete=models.SET_NULL, null=True, blank=True, related_name="dividas"
    )
    tipo = models.CharField(max_length=25, choices=TipoDivida.choices)
    descricao = models.CharField(max_length=180)
    saldo_devedor = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(0)]
    )
    taxa_juros_mensal = models.DecimalField(
        max_digits=6, decimal_places=3, default=0, help_text="Em % ao mês."
    )
    parcelas_restantes = models.PositiveIntegerField(default=0)
    valor_parcela = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    titularidade = models.CharField(
        max_length=20, choices=Titularidade.choices, default=Titularidade.TITULAR
    )

    # --- Dados do financiamento (para simular quitação/amortização) ---------
    sistema = models.CharField(
        max_length=10,
        choices=SistemaAmortizacao.choices,
        default=SistemaAmortizacao.PRICE,
        help_text="Price é o padrão em financiamento de veículo; SAC, em imóvel pela Caixa.",
    )
    parcelas_totais = models.PositiveIntegerField(
        default=0, help_text="Prazo contratado, em meses."
    )
    data_primeira_parcela = models.DateField(
        null=True,
        blank=True,
        help_text="Permite calcular quantas parcelas já foram pagas.",
    )
    valor_financiado = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        help_text="Valor original do contrato, antes de qualquer pagamento.",
    )

    class Meta:
        verbose_name = "dívida"
        verbose_name_plural = "dívidas"

    def __str__(self) -> str:
        return self.descricao

    @property
    def parcelas_pagas(self) -> int:
        """Quantas parcelas já venceram.

        Prioriza a data da primeira parcela, que é o dado mais confiável: o
        saldo devedor e as parcelas restantes são informados de memória e
        envelhecem a cada mês que passa sem o cliente atualizar.
        """
        if self.data_primeira_parcela:
            hoje = date.today()
            meses = (hoje.year - self.data_primeira_parcela.year) * 12 + (
                hoje.month - self.data_primeira_parcela.month
            )
            if hoje.day >= self.data_primeira_parcela.day:
                meses += 1
            decorridas = max(meses, 0)
            if self.parcelas_totais:
                return min(decorridas, self.parcelas_totais)
            return decorridas
        if self.parcelas_totais and self.parcelas_restantes:
            return max(self.parcelas_totais - self.parcelas_restantes, 0)
        return 0

    @property
    def parcelas_a_pagar(self) -> int:
        if self.parcelas_totais:
            return max(self.parcelas_totais - self.parcelas_pagas, 0)
        return self.parcelas_restantes

    @property
    def progresso_percentual(self) -> Decimal:
        if not self.parcelas_totais:
            return Decimal("0.00")
        pct = Decimal(self.parcelas_pagas) / Decimal(self.parcelas_totais) * 100
        return min(pct, Decimal("100")).quantize(Decimal("0.01"))

    @property
    def data_quitacao_prevista(self) -> date | None:
        """Vencimento da última parcela, no ritmo atual."""
        if not self.data_primeira_parcela or not self.parcelas_totais:
            return None
        meses = self.parcelas_totais - 1
        ano = self.data_primeira_parcela.year + (self.data_primeira_parcela.month - 1 + meses) // 12
        mes = (self.data_primeira_parcela.month - 1 + meses) % 12 + 1
        dia = min(self.data_primeira_parcela.day, monthrange(ano, mes)[1])
        return date(ano, mes, dia)


class CategoriaObjetivo(models.TextChoices):
    APOSENTADORIA = "aposentadoria", "Aposentadoria"
    IMOVEL = "imovel", "Compra de imóvel"
    FACULDADE_FILHOS = "faculdade_filhos", "Faculdade dos filhos"
    SUCESSAO = "sucessao", "Sucessão patrimonial"
    RESERVA = "reserva", "Reserva de emergência"
    OUTRO = "outro", "Outro"


class LifeGoal(TenantScopedModel):
    """Objetivo de vida coletado no onboarding (insumo das Metas — seção 3.5)."""

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="objetivos"
    )
    membro = models.ForeignKey(
        Member,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="objetivos",
        help_text="Nulo quando o objetivo é do casal/família.",
    )
    categoria = models.CharField(max_length=25, choices=CategoriaObjetivo.choices)
    descricao = models.CharField(max_length=255)
    horizonte_anos = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "objetivo de vida"
        verbose_name_plural = "objetivos de vida"

    def __str__(self) -> str:
        return self.descricao
