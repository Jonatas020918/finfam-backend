"""Administração de planos e assinaturas.

O admin é a única interface por onde os planos são ligados ao Stripe: os
identificadores de preço e de cupom nascem lá e precisam ser transcritos para
cá. Sem esta tela, a integração de cobrança fica sem ponto de encontro.
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import DadosFiscais, Plan, Subscription


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = (
        "nome",
        "codigo",
        "preco_de_entrada_exibido",
        "preco_mensal",
        "disponivel",
        "conectado_ao_stripe",
        "ordem",
    )
    list_filter = ("disponivel", "ativo")
    list_editable = ("disponivel", "ordem")
    ordering = ("ordem",)

    fieldsets = (
        (None, {"fields": ("codigo", "nome", "descricao", "ordem")}),
        (
            "Preço",
            {
                "fields": (
                    "preco_mensal",
                    "preco_promocional",
                    "meses_promocionais",
                    "preco_anual",
                ),
                "description": (
                    "O <b>preço mensal</b> é o valor cheio, que vale depois da promoção. "
                    "O <b>preço promocional</b> vale pelos <b>meses promocionais</b> "
                    "iniciais. É o valor cheio que vai para o Price do Stripe; a "
                    "diferença entre os dois vira o cupom."
                ),
            },
        ),
        (
            "Disponibilidade",
            {
                "fields": ("ativo", "disponivel", "recursos"),
                "description": (
                    "<b>Ativo</b> mostra o plano na vitrine. <b>Disponível</b> permite "
                    "assinar — um plano ativo e indisponível aparece como “em breve”, "
                    "e o servidor recusa a assinatura."
                ),
            },
        ),
        (
            "Stripe",
            {
                "fields": ("stripe_price_id", "stripe_coupon_id"),
                "description": (
                    "Copie do painel do Stripe. O <b>price</b> (começa com "
                    "<code>price_</code>) fica na página do produto, no valor recorrente "
                    "com o preço cheio. O <b>coupon</b> é o desconto com duração "
                    "repetida que cobre a diferença até o promocional.<br><br>"
                    "Sem o price, a cobrança falha — e falha antes de chamar o Stripe, "
                    "para a mensagem dizer qual plano ficou pela metade.<br><br>"
                    "<b>Teste e produção têm identificadores diferentes.</b> Ao virar "
                    "a chave para produção, estes dois campos precisam ser trocados."
                ),
            },
        ),
    )

    @admin.display(description="entrada")
    def preco_de_entrada_exibido(self, obj):
        """O que o cliente paga no primeiro mês."""
        if obj.em_promocao:
            return format_html(
                "<b>R$ {}</b> <span style='color:#666'>× {} meses</span>",
                obj.preco_promocional,
                obj.meses_promocionais,
            )
        return f"R$ {obj.preco_mensal}"

    @admin.display(description="Stripe", boolean=True)
    def conectado_ao_stripe(self, obj):
        """Enxergar de relance qual plano ainda não cobra.

        Um plano disponível sem price cadastrado é uma venda que falha na hora
        do pagamento — vale ver isso na lista, não só ao abrir o registro.
        """
        return bool(obj.stripe_price_id)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    """Consulta de suporte: por que este cliente está bloqueado?"""

    list_display = (
        "household",
        "plano",
        "status",
        "acesso",
        "dias_restantes",
        "proxima_cobranca",
        "gateway",
    )
    list_filter = ("status", "gateway", "plano")
    search_fields = ("household__nome", "gateway_customer_id", "gateway_subscription_id")
    date_hierarchy = "inicio"

    readonly_fields = ("criado_em", "atualizado_em", "motivo_do_bloqueio_exibido")

    fieldsets = (
        (None, {"fields": ("household", "tenant", "plano", "periodicidade")}),
        (
            "Situação",
            {
                "fields": (
                    "status",
                    "motivo_do_bloqueio_exibido",
                    "inicio",
                    "trial_termina_em",
                    "carencia_ate",
                    "proxima_cobranca",
                    "promocao_ate",
                    "cancelada_em",
                ),
            },
        ),
        (
            "Gateway",
            {
                "fields": ("gateway", "gateway_customer_id", "gateway_subscription_id"),
                "description": (
                    "Preenchidos pelo webhook quando o pagamento é confirmado. "
                    "O <code>customer</code> é o que permite abrir o portal de "
                    "pagamento do cliente."
                ),
            },
        ),
        ("Registro", {"fields": ("criado_em", "atualizado_em"), "classes": ("collapse",)}),
    )

    @admin.display(description="acesso", boolean=True)
    def acesso(self, obj):
        return obj.da_acesso

    @admin.display(description="motivo do bloqueio")
    def motivo_do_bloqueio_exibido(self, obj):
        return obj.motivo_do_bloqueio or "— com acesso liberado"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("household", "plano")


@admin.register(DadosFiscais)
class DadosFiscaisAdmin(admin.ModelAdmin):
    list_display = ("household", "documento", "cidade", "uf", "completo_exibido")
    search_fields = ("household__nome", "documento", "razao_social")

    @admin.display(description="pronto para nota", boolean=True)
    def completo_exibido(self, obj):
        return obj.completo
