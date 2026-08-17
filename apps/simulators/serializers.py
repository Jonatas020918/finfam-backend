from decimal import Decimal

from rest_framework import serializers

from .models import SimulationRun


class EntradaSimulacaoSerializer(serializers.Serializer):
    receita_bruta_mensal = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01")
    )
    dependentes = serializers.IntegerField(min_value=0, default=0)
    beneficios_nao_tributaveis_mensais = serializers.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0"), min_value=Decimal("0")
    )
    pro_labore_mensal = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True, min_value=Decimal("0")
    )
    despesas_pj_mensais = serializers.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0"), min_value=Decimal("0")
    )
    anexo_simples = serializers.ChoiceField(choices=["auto", "III", "V"], default="auto")
    despesas_livro_caixa_mensais = serializers.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0"), min_value=Decimal("0")
    )
    inss_autonomo_retido_na_fonte = serializers.BooleanField(default=False)
    # Persistência opcional: quando informado, o resultado fica no histórico.
    membro = serializers.UUIDField(required=False, allow_null=True)
    salvar = serializers.BooleanField(default=False)


class EntradaAmortizacaoSerializer(serializers.Serializer):
    """Entrada do simulador de quitação.

    Ou se informa `divida` (e os dados vêm do cadastro), ou se informam saldo,
    taxa e prazo manualmente — útil para avaliar um financiamento antes mesmo
    de contratá-lo.
    """

    divida = serializers.UUIDField(required=False, allow_null=True)
    saldo_devedor = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, min_value=Decimal("0.01")
    )
    taxa_juros_mensal = serializers.DecimalField(
        max_digits=6, decimal_places=3, required=False, min_value=Decimal("0")
    )
    parcelas_restantes = serializers.IntegerField(required=False, min_value=1, max_value=600)
    sistema = serializers.ChoiceField(choices=["price", "sac"], default="price")

    aporte_extra_mensal = serializers.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0"), min_value=Decimal("0")
    )
    aporte_unico = serializers.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0"), min_value=Decimal("0")
    )
    estrategia = serializers.ChoiceField(
        choices=["reduzir_prazo", "reduzir_parcela"], default="reduzir_prazo"
    )

    def validate(self, attrs):
        if attrs.get("divida"):
            return attrs
        faltando = [
            campo
            for campo in ("saldo_devedor", "taxa_juros_mensal", "parcelas_restantes")
            if attrs.get(campo) is None
        ]
        if faltando:
            raise serializers.ValidationError(
                {
                    campo: "Obrigatório quando nenhuma dívida cadastrada é informada."
                    for campo in faltando
                }
            )
        return attrs


class EntradaProjecaoSerializer(serializers.Serializer):
    """Parâmetros da projeção — todos com padrão utilizável."""

    meses_base = serializers.IntegerField(
        default=12,
        min_value=1,
        max_value=24,
        help_text="Quantos meses de histórico formam a média.",
    )
    anos = serializers.IntegerField(
        default=10, min_value=1, max_value=15, help_text="Horizonte da projeção."
    )
    rentabilidade_real_anual = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("4"),
        min_value=Decimal("-10"),
        max_value=Decimal("30"),
        help_text="Retorno acima da inflação, em % ao ano.",
    )
    crescimento_renda_anual = serializers.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0"),
        min_value=Decimal("-20"), max_value=Decimal("50"),
    )
    inflacao_despesas_anual = serializers.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0"),
        min_value=Decimal("-20"), max_value=Decimal("50"),
    )
    aporte_mensal_manual = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=Decimal("0"),
        help_text="Substitui a sobra observada, para testar um plano de aportes.",
    )


class SimulationRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = SimulationRun
        fields = ["id", "membro", "entrada", "resultado", "versao_regras", "criado_em"]
        read_only_fields = fields
