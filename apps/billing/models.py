"""Assinaturas.

O modelo é deliberadamente independente do meio de pagamento: guarda o **estado
comercial** (em teste, ativa, em carência, cancelada) e apenas referencia o
gateway por identificadores opacos. Trocar de provedor, ou começar cobrando na
mão e migrar depois, não deve exigir mexer em regra de acesso.

Quem decide se o cliente entra na plataforma é `da_acesso`, e só ela — nenhuma
tela replica essa conta.
"""

from datetime import date, timedelta

from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class PlanoCodigo(models.TextChoices):
    BASICO = "basico", "Básico"
    INTERMEDIARIO = "intermediario", "Intermediário"
    CONSULTOR = "consultor", "Com consultor"


class Plan(TimeStampedModel):
    """Plano comercial.

    O preço promocional não é um desconto pontual: é o preço de entrada por um
    número definido de meses, depois do qual o valor cheio assume. Guardar os
    dois separadamente — em vez de só o valor vigente — permite mostrar ao
    cliente exatamente o que ele vai pagar e quando isso muda, que é a
    informação que evita cancelamento por surpresa.
    """

    codigo = models.CharField(max_length=25, choices=PlanoCodigo.choices, unique=True)
    nome = models.CharField(max_length=120)
    descricao = models.TextField(blank=True)

    preco_mensal = models.DecimalField(
        max_digits=10, decimal_places=2, help_text="Valor cheio, após a promoção."
    )
    preco_promocional = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    meses_promocionais = models.PositiveSmallIntegerField(
        default=0, help_text="Por quantos meses o preço promocional vale."
    )
    preco_anual = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Em branco quando o plano não é vendido no anual.",
    )

    # Recursos exibidos na tela. Cada item: {"texto": ..., "em_breve": bool}
    recursos = models.JSONField(default=list, blank=True)

    ativo = models.BooleanField(default=True, help_text="Aparece na vitrine.")
    disponivel = models.BooleanField(
        default=False,
        help_text="Pode ser assinado agora. Falso = anunciado como 'em breve'.",
    )
    ordem = models.PositiveSmallIntegerField(default=0)

    # Identificadores do Stripe. A promoção é um cupom com duração de N meses.
    stripe_price_id = models.CharField(max_length=120, blank=True)
    stripe_coupon_id = models.CharField(max_length=120, blank=True)

    class Meta:
        verbose_name = "plano"
        verbose_name_plural = "planos"
        ordering = ["ordem", "preco_mensal"]

    def __str__(self) -> str:
        return self.nome

    @property
    def em_promocao(self) -> bool:
        return bool(self.preco_promocional and self.meses_promocionais)

    @property
    def preco_de_entrada(self):
        """O que o cliente paga na primeira cobrança."""
        return self.preco_promocional if self.em_promocao else self.preco_mensal


class StatusAssinatura(models.TextChoices):
    TRIAL = "trial", "Período de teste"
    ATIVA = "ativa", "Ativa"
    # Cobrança falhou, mas o cliente ainda entra: é a carência.
    INADIMPLENTE = "inadimplente", "Inadimplente (em carência)"
    SUSPENSA = "suspensa", "Suspensa por falta de pagamento"
    CANCELADA = "cancelada", "Cancelada"


class Periodicidade(models.TextChoices):
    MENSAL = "mensal", "Mensal"
    ANUAL = "anual", "Anual"


class Subscription(TimeStampedModel):
    """Assinatura de um núcleo familiar (Fase 1) ou de um consultor (Fase 3)."""

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
    plano = models.ForeignKey(
        Plan, on_delete=models.PROTECT, related_name="assinaturas", null=True, blank=True
    )
    periodicidade = models.CharField(
        max_length=10, choices=Periodicidade.choices, default=Periodicidade.MENSAL
    )

    status = models.CharField(
        max_length=20, choices=StatusAssinatura.choices, default=StatusAssinatura.TRIAL
    )
    inicio = models.DateField(default=date.today)
    trial_termina_em = models.DateField(null=True, blank=True)
    # Até quando o inadimplente continua entrando. Nulo fora da carência.
    carencia_ate = models.DateField(null=True, blank=True)
    proxima_cobranca = models.DateField(null=True, blank=True)
    cancelada_em = models.DateField(null=True, blank=True)
    # Até quando vale o preço de entrada. Depois disso o valor cheio assume.
    promocao_ate = models.DateField(null=True, blank=True)

    # --- Gateway: identificadores opacos, sem regra de negócio -------------
    gateway = models.CharField(
        max_length=40,
        blank=True,
        help_text="Vazio enquanto a cobrança é feita manualmente.",
    )
    gateway_customer_id = models.CharField(max_length=120, blank=True)
    gateway_subscription_id = models.CharField(max_length=120, blank=True)

    class Meta:
        verbose_name = "assinatura"
        verbose_name_plural = "assinaturas"
        ordering = ["-criado_em"]

    def __str__(self) -> str:
        alvo = self.household or self.tenant
        return f"{self.get_status_display()} — {alvo}"

    # --- Regras de acesso ---------------------------------------------------

    @property
    def da_acesso(self) -> bool:
        """Única fonte de verdade sobre entrar ou não na plataforma."""
        hoje = date.today()

        if self.status == StatusAssinatura.ATIVA:
            return True
        if self.status == StatusAssinatura.TRIAL:
            return self.trial_termina_em is None or hoje <= self.trial_termina_em
        if self.status == StatusAssinatura.INADIMPLENTE:
            # Em carência o acesso continua, com aviso na tela.
            return self.carencia_ate is not None and hoje <= self.carencia_ate
        return False

    @property
    def em_teste(self) -> bool:
        return self.status == StatusAssinatura.TRIAL and self.da_acesso

    @property
    def em_carencia(self) -> bool:
        return self.status == StatusAssinatura.INADIMPLENTE and self.da_acesso

    @property
    def dias_restantes(self) -> int | None:
        """Dias até perder o acesso. Nulo quando não há prazo correndo."""
        limite = None
        if self.status == StatusAssinatura.TRIAL:
            limite = self.trial_termina_em
        elif self.status == StatusAssinatura.INADIMPLENTE:
            limite = self.carencia_ate
        if limite is None:
            return None
        return max((limite - date.today()).days, 0)

    @property
    def motivo_do_bloqueio(self) -> str | None:
        """Texto exibido ao cliente quando o acesso é negado."""
        if self.da_acesso:
            return None
        if self.status == StatusAssinatura.TRIAL:
            return "Seu período de teste terminou. Escolha um plano para continuar."
        if self.status in {StatusAssinatura.INADIMPLENTE, StatusAssinatura.SUSPENSA}:
            return (
                "Não conseguimos confirmar o pagamento da sua assinatura. "
                "Regularize para voltar a usar a plataforma."
            )
        return "Sua assinatura está cancelada. Reative para continuar."

    # --- Transições ---------------------------------------------------------

    def iniciar_carencia(self, dias: int | None = None) -> None:
        """Cobrança falhou: mantém o acesso por alguns dias, com aviso."""
        dias = settings.ASSINATURA_CARENCIA_DIAS if dias is None else dias
        self.status = StatusAssinatura.INADIMPLENTE
        self.carencia_ate = date.today() + timedelta(days=dias)
        self.save(update_fields=["status", "carencia_ate", "atualizado_em"])

    def ativar(self, proxima_cobranca: date | None = None) -> None:
        self.status = StatusAssinatura.ATIVA
        self.carencia_ate = None
        self.cancelada_em = None
        if proxima_cobranca:
            self.proxima_cobranca = proxima_cobranca
        self.save(
            update_fields=[
                "status", "carencia_ate", "cancelada_em", "proxima_cobranca", "atualizado_em"
            ]
        )

    def suspender(self) -> None:
        """Fim da carência sem pagamento: acesso cortado, dados preservados."""
        self.status = StatusAssinatura.SUSPENSA
        self.carencia_ate = None
        self.save(update_fields=["status", "carencia_ate", "atualizado_em"])

    def cancelar(self) -> None:
        self.status = StatusAssinatura.CANCELADA
        self.cancelada_em = date.today()
        self.carencia_ate = None
        self.save(update_fields=["status", "cancelada_em", "carencia_ate", "atualizado_em"])


class DadosFiscais(TimeStampedModel):
    """Dados para emissão de NFS-e.

    Ficam separados do cadastro do cliente porque só existem para quem paga, e
    porque a emissão é obrigação municipal — nenhum gateway faz isso por nós.
    Coletar desde já evita ter que pedir depois, no pior momento: o da compra.
    """

    household = models.OneToOneField(
        "households.Household", on_delete=models.CASCADE, related_name="dados_fiscais"
    )
    razao_social = models.CharField(max_length=180, blank=True)
    documento = models.CharField(max_length=20, help_text="CPF ou CNPJ, somente números.")
    inscricao_municipal = models.CharField(max_length=30, blank=True)

    cep = models.CharField(max_length=9, blank=True)
    logradouro = models.CharField(max_length=180, blank=True)
    numero = models.CharField(max_length=20, blank=True)
    complemento = models.CharField(max_length=80, blank=True)
    bairro = models.CharField(max_length=120, blank=True)
    cidade = models.CharField(max_length=120, blank=True)
    uf = models.CharField(max_length=2, blank=True)

    class Meta:
        verbose_name = "dados fiscais"
        verbose_name_plural = "dados fiscais"

    def __str__(self) -> str:
        return f"{self.razao_social or self.household.nome} ({self.documento})"

    @property
    def completo(self) -> bool:
        """A nota só pode ser emitida com endereço e documento."""
        return bool(self.documento and self.cep and self.logradouro and self.cidade and self.uf)
