from rest_framework import serializers

from .models import CashFlowEntry


class CashFlowEntrySerializer(serializers.ModelSerializer):
    membro_nome = serializers.CharField(source="membro.nome", read_only=True)
    compartilhado = serializers.BooleanField(read_only=True)

    class Meta:
        model = CashFlowEntry
        fields = [
            "id",
            "membro",
            "membro_nome",
            "compartilhado",
            "tipo",
            "categoria",
            "descricao",
            "valor_realizado",
            "valor_orcado",
            "ano",
            "mes",
        ]

    def validate_membro(self, membro):
        if membro is None:
            return membro
        household = self.context.get("household")
        if household and membro.household_id != household.id:
            raise serializers.ValidationError("Membro não pertence a este núcleo familiar.")
        return membro

    def validate(self, attrs):
        mes = attrs.get("mes", getattr(self.instance, "mes", None))
        if mes is not None and not 1 <= mes <= 12:
            raise serializers.ValidationError({"mes": "Mês deve estar entre 1 e 12."})
        return attrs


class ResumoMembroSerializer(serializers.Serializer):
    membro_id = serializers.CharField(allow_null=True)
    membro_nome = serializers.CharField()
    receitas = serializers.DecimalField(max_digits=14, decimal_places=2)
    despesas = serializers.DecimalField(max_digits=14, decimal_places=2)
    saldo = serializers.DecimalField(max_digits=14, decimal_places=2)


class ResumoMensalSerializer(serializers.Serializer):
    """Fluxo de caixa consolidado do mês, com quebra por membro (seção 3.2)."""

    ano = serializers.IntegerField()
    mes = serializers.IntegerField()
    receitas_realizadas = serializers.DecimalField(max_digits=14, decimal_places=2)
    despesas_realizadas = serializers.DecimalField(max_digits=14, decimal_places=2)
    saldo_realizado = serializers.DecimalField(max_digits=14, decimal_places=2)
    receitas_orcadas = serializers.DecimalField(max_digits=14, decimal_places=2)
    despesas_orcadas = serializers.DecimalField(max_digits=14, decimal_places=2)
    saldo_orcado = serializers.DecimalField(max_digits=14, decimal_places=2)
    taxa_poupanca = serializers.DecimalField(max_digits=6, decimal_places=2)
    por_categoria = serializers.DictField()
    por_membro = ResumoMembroSerializer(many=True)
