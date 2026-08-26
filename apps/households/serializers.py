from rest_framework import serializers

from .models import (
    Asset,
    Debt,
    Household,
    IncomeSource,
    LifeGoal,
    Member,
    TipoDivida,
    TipoMembro,
)


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
    detalhada = serializers.BooleanField(read_only=True)
    media_realizada = serializers.SerializerMethodField()

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
            "valor_e_bruto",
            "variabilidade_percentual",
            "modo_lancamento",
            "detalhada",
            "media_realizada",
            "ativa",
        ]

    def get_media_realizada(self, obj) -> str | None:
        if not obj.detalhada:
            return None
        media = obj.media_realizada()
        return str(media) if media is not None else None

    def validate_membro(self, membro):
        household = self.context.get("household")
        if household and membro.household_id != household.id:
            raise serializers.ValidationError("Membro não pertence a este núcleo familiar.")
        if not membro.pode_gerar_renda:
            raise serializers.ValidationError(
                "Dependentes não possuem fontes de renda próprias."
            )
        return membro


class LancamentoCompetenciaSerializer(serializers.Serializer):
    """Quanto uma fonte rendeu em um mês específico."""

    ano = serializers.IntegerField(min_value=2000, max_value=2100)
    mes = serializers.IntegerField(min_value=1, max_value=12)
    valor_realizado = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0
    )


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

    # Teto de 20% ao mês. O cheque especial, que é o crédito mais caro do
    # mercado brasileiro, fica perto de 8%; 20% dá folga larga para qualquer
    # dívida real e ainda barra o dedo que erra a casa decimal. Sem teto, um
    # "999" digitado por engano gera um cronograma de amortização absurdo e o
    # cliente conclui que a conta da plataforma está errada.
    # `required=False` e `default` acompanham o modelo: declarar o campo aqui
    # o tornaria obrigatório, e quem cadastra uma dívida sem juros informados
    # passaria a receber 400 onde antes gravava.
    taxa_juros_mensal = serializers.DecimalField(
        max_digits=6, decimal_places=3, min_value=0, max_value=20,
        required=False, default=0,
        help_text="Em % ao mês, entre 0 e 20.",
    )

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

    #: Dívidas que realmente não têm data para acabar. Cartão e "outra" giram
    #: enquanto houver saldo; financiamento tem número de parcelas por
    #: contrato, e tratar os dois igual é o que deixa a parcela eterna.
    SEM_FIM_PREVISTO = {TipoDivida.CARTAO, TipoDivida.OUTRA}

    def validate(self, attrs):
        """Financiamento precisa dizer quantas parcelas faltam.

        Sem isso, "não sei quantas faltam" e "não tem fim" ficam escritos do
        mesmo jeito — zero. E o zero é lido como rotativo: a parcela vira uma
        despesa fixa sem vigência final, saindo do orçamento todos os meses,
        inclusive anos depois de o bem estar quitado. Aconteceu em produção,
        com um financiamento de veículo.
        """
        instancia = self.instance
        pega = lambda campo, padrao=None: attrs.get(  # noqa: E731
            campo, getattr(instancia, campo, padrao)
        )

        tipo = pega("tipo")
        if tipo in self.SEM_FIM_PREVISTO:
            return attrs

        saldo = pega("saldo_devedor") or 0
        parcela = pega("valor_parcela") or 0
        restantes = pega("parcelas_restantes") or 0

        if saldo > 0 and parcela > 0 and restantes <= 0:
            raise serializers.ValidationError(
                {
                    "parcelas_restantes": (
                        "Informe quantas parcelas ainda faltam. Sem isso a parcela "
                        "entraria no orçamento como despesa sem fim, continuando a "
                        "sair mesmo depois de a dívida estar quitada. Se esta dívida "
                        "não tem número de parcelas definido, cadastre-a como cartão "
                        "de crédito ou como outra."
                    )
                }
            )
        return attrs


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
