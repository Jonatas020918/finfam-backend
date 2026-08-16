from rest_framework import serializers

from .models import CashFlowEntry, TipoLancamento


class CashFlowEntrySerializer(serializers.ModelSerializer):
    membro_nome = serializers.CharField(source="membro.nome", read_only=True)
    compartilhado = serializers.BooleanField(read_only=True)
    fonte_renda_descricao = serializers.CharField(source="fonte_renda.descricao", read_only=True)
    regime_display = serializers.CharField(source="get_regime_display", read_only=True)
    tipo_renda_display = serializers.CharField(source="get_tipo_renda_display", read_only=True)

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
            "fonte_renda",
            "fonte_renda_descricao",
            "regime",
            "regime_display",
            "tipo_renda",
            "tipo_renda_display",
        ]

    def validate_membro(self, membro):
        if membro is None:
            return membro
        household = self.context.get("household")
        if household and membro.household_id != household.id:
            raise serializers.ValidationError("Membro não pertence a este núcleo familiar.")
        return membro

    def validate_fonte_renda(self, fonte):
        if fonte is None:
            return fonte
        household = self.context.get("household")
        if household and fonte.household_id != household.id:
            raise serializers.ValidationError(
                "Fonte de renda não pertence a este núcleo familiar."
            )
        return fonte

    def _valor_atual(self, attrs, campo):
        return attrs.get(campo, getattr(self.instance, campo, None))

    def validate(self, attrs):
        mes = self._valor_atual(attrs, "mes")
        if mes is not None and not 1 <= mes <= 12:
            raise serializers.ValidationError({"mes": "Mês deve estar entre 1 e 12."})

        tipo = self._valor_atual(attrs, "tipo")
        fonte = self._valor_atual(attrs, "fonte_renda")
        regime = self._valor_atual(attrs, "regime")
        tipo_renda = self._valor_atual(attrs, "tipo_renda")

        if tipo == TipoLancamento.DESPESA:
            # Despesa não tem regime tributário — deixar o campo preenchido aqui
            # contaminaria os totais por regime usados pelo simulador.
            if fonte or regime or tipo_renda:
                raise serializers.ValidationError(
                    {"regime": "Classificação de renda só se aplica a receitas."}
                )
            return attrs

        if fonte is not None:
            membro = self._valor_atual(attrs, "membro")
            if membro is not None and membro.id != fonte.membro_id:
                raise serializers.ValidationError(
                    {"membro": "A fonte de renda selecionada pertence a outro membro."}
                )
            # A fonte é a origem da verdade: regime, tipo e membro vêm dela.
            attrs["membro"] = fonte.membro
            attrs["regime"] = fonte.regime
            attrs["tipo_renda"] = fonte.tipo

        return attrs


class ResumoMembroSerializer(serializers.Serializer):
    membro_id = serializers.CharField(allow_null=True)
    membro_nome = serializers.CharField()
    receitas = serializers.DecimalField(max_digits=14, decimal_places=2)
    despesas = serializers.DecimalField(max_digits=14, decimal_places=2)
    saldo = serializers.DecimalField(max_digits=14, decimal_places=2)


class ResumoRegimeSerializer(serializers.Serializer):
    """Receitas do mês agrupadas por regime tributário."""

    regime = serializers.CharField()
    rotulo = serializers.CharField()
    receitas = serializers.DecimalField(max_digits=14, decimal_places=2)
    participacao_percentual = serializers.DecimalField(max_digits=6, decimal_places=2)


class ResumoFonteSerializer(serializers.Serializer):
    fonte_id = serializers.CharField(allow_null=True)
    descricao = serializers.CharField()
    membro_nome = serializers.CharField(allow_null=True)
    regime = serializers.CharField(allow_blank=True)
    tipo_renda = serializers.CharField(allow_blank=True)
    receitas = serializers.DecimalField(max_digits=14, decimal_places=2)


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
    por_regime = ResumoRegimeSerializer(many=True)
    por_fonte = ResumoFonteSerializer(many=True)
    receitas_nao_classificadas = serializers.DecimalField(max_digits=14, decimal_places=2)
