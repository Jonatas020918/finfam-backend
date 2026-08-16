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


class SimulationRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = SimulationRun
        fields = ["id", "membro", "entrada", "resultado", "versao_regras", "criado_em"]
        read_only_fields = fields
