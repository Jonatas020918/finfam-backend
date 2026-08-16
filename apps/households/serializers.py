from rest_framework import serializers

from .models import Asset, Debt, Household, IncomeSource, LifeGoal, Member, TipoMembro


class MemberSerializer(serializers.ModelSerializer):
    pode_gerar_renda = serializers.BooleanField(read_only=True)
    tem_login = serializers.SerializerMethodField()

    class Meta:
        model = Member
        fields = [
            "id",
            "tipo",
            "nome",
            "data_nascimento",
            "profissao",
            "evento_futuro",
            "evento_futuro_ano",
            "pode_gerar_renda",
            "tem_login",
        ]

    def get_tem_login(self, obj) -> bool:
        return obj.usuario_id is not None

    def validate_tipo(self, value):
        """Impede um segundo titular — a constraint do banco existe, mas o erro
        precisa chegar ao usuário como validação, não como erro 500."""
        if value != TipoMembro.TITULAR:
            return value
        household = self.context.get("household")
        qs = Member.objects.filter(household=household, tipo=TipoMembro.TITULAR)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if household and qs.exists():
            raise serializers.ValidationError(
                "Já existe um titular neste núcleo familiar."
            )
        return value


class IncomeSourceSerializer(serializers.ModelSerializer):
    membro_nome = serializers.CharField(source="membro.nome", read_only=True)

    class Meta:
        model = IncomeSource
        fields = [
            "id",
            "membro",
            "membro_nome",
            "descricao",
            "tipo",
            "regime",
            "valor_medio_mensal",
            "variabilidade_percentual",
            "ativa",
        ]

    def validate_membro(self, membro):
        household = self.context.get("household")
        if household and membro.household_id != household.id:
            raise serializers.ValidationError("Membro não pertence a este núcleo familiar.")
        if not membro.pode_gerar_renda:
            raise serializers.ValidationError(
                "Dependentes não possuem fontes de renda próprias."
            )
        return membro


class _MembroDoHouseholdMixin:
    """Valida que o `membro` informado pertence ao núcleo familiar do usuário."""

    def validate_membro(self, membro):
        if membro is None:
            return membro
        household = self.context.get("household")
        if household and membro.household_id != household.id:
            raise serializers.ValidationError("Membro não pertence a este núcleo familiar.")
        return membro


class AssetSerializer(_MembroDoHouseholdMixin, serializers.ModelSerializer):
    class Meta:
        model = Asset
        fields = [
            "id",
            "membro",
            "tipo",
            "descricao",
            "valor_atual",
            "titularidade",
            "detentor_juridico",
        ]


class DebtSerializer(_MembroDoHouseholdMixin, serializers.ModelSerializer):
    parcelas_pagas = serializers.IntegerField(read_only=True)
    parcelas_a_pagar = serializers.IntegerField(read_only=True)
    progresso_percentual = serializers.DecimalField(
        max_digits=6, decimal_places=2, read_only=True
    )
    data_quitacao_prevista = serializers.DateField(read_only=True)

    class Meta:
        model = Debt
        fields = [
            "id",
            "membro",
            "tipo",
            "descricao",
            "saldo_devedor",
            "taxa_juros_mensal",
            "parcelas_restantes",
            "valor_parcela",
            "titularidade",
            "sistema",
            "parcelas_totais",
            "data_primeira_parcela",
            "valor_financiado",
            # Calculados no servidor — o cliente nunca precisa fazer essa conta.
            "parcelas_pagas",
            "parcelas_a_pagar",
            "progresso_percentual",
            "data_quitacao_prevista",
        ]


class LifeGoalSerializer(_MembroDoHouseholdMixin, serializers.ModelSerializer):
    class Meta:
        model = LifeGoal
        fields = ["id", "membro", "categoria", "descricao", "horizonte_anos"]


class HouseholdSerializer(serializers.ModelSerializer):
    membros = MemberSerializer(many=True, read_only=True)
    onboarding_concluido = serializers.BooleanField(read_only=True)

    class Meta:
        model = Household
        fields = [
            "id",
            "nome",
            "modo",
            "estado_civil",
            "regime_bens",
            "onboarding_concluido",
            "onboarding_concluido_em",
            "membros",
        ]
        read_only_fields = ["id", "modo", "onboarding_concluido_em"]
