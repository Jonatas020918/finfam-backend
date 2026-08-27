from datetime import date
from decimal import Decimal

from rest_framework import serializers

from apps.households.models import RegimeTributario

from .liquido import calcular_retencao_clt, dependentes_do_household
from .models import CashFlowEntry, RecurringExpense, TipoLancamento


class RecurringExpenseSerializer(serializers.ModelSerializer):
    membro_nome = serializers.CharField(source="membro.nome", read_only=True)
    divida_descricao = serializers.CharField(source="divida.descricao", read_only=True)

    class Meta:
        model = RecurringExpense
        fields = [
            "id",
            "descricao",
            "categoria",
            "valor_previsto",
            "membro",
            "membro_nome",
            "dia_vencimento",
            "vigencia_inicio",
            "vigencia_fim",
            "ativa",
            "divida",
            "divida_descricao",
        ]

    def validate_membro(self, membro):
        if membro is None:
            return membro
        household = self.context.get("household")
        if household and membro.household_id != household.id:
            raise serializers.ValidationError("Membro não pertence a este núcleo familiar.")
        return membro

    def validate_divida(self, divida):
        if divida is None:
            return divida
        household = self.context.get("household")
        if household and divida.household_id != household.id:
            raise serializers.ValidationError("Dívida não pertence a este núcleo familiar.")
        return divida

    def validate(self, attrs):
        inicio = attrs.get("vigencia_inicio", getattr(self.instance, "vigencia_inicio", None))
        fim = attrs.get("vigencia_fim", getattr(self.instance, "vigencia_fim", None))
        if inicio and fim and fim < inicio:
            raise serializers.ValidationError(
                {"vigencia_fim": "O fim da vigência não pode ser anterior ao início."}
            )
        return attrs


class AbrirCompetenciaSerializer(serializers.Serializer):
    """Abertura de um mês de competência.

    O limite superior não é o ano 2100: é o mês corrente. Abrir competência
    materializa lançamentos de verdade, e um mês que ainda não aconteceu não
    tem o que registrar — o valor "realizado" de dezembro que vem não existe.

    A tela já impede escolher o futuro. Esta validação existe porque a tela não
    é uma barreira: quem chamar a API direto entra pelo mesmo caminho, e o que
    entra aqui vira linha no banco do cliente.
    """

    ano = serializers.IntegerField(min_value=2000, max_value=2100)
    mes = serializers.IntegerField(min_value=1, max_value=12)

    def validate(self, dados):
        hoje = date.today()
        pedido = dados["ano"] * 12 + dados["mes"]
        limite = hoje.year * 12 + hoje.month

        if pedido > limite:
            raise serializers.ValidationError(
                "Não é possível abrir uma competência futura: "
                f"o mês mais recente disponível é {hoje.month:02d}/{hoje.year}."
            )
        return dados


class CashFlowEntrySerializer(serializers.ModelSerializer):
    membro_nome = serializers.CharField(source="membro.nome", read_only=True)
    compartilhado = serializers.BooleanField(read_only=True)
    fonte_renda_descricao = serializers.CharField(source="fonte_renda.descricao", read_only=True)
    regime_display = serializers.CharField(source="get_regime_display", read_only=True)
    tipo_renda_display = serializers.CharField(source="get_tipo_renda_display", read_only=True)
    recorrente = serializers.BooleanField(read_only=True)
    # Calculado pelo servidor a partir da fonte de renda, nunca digitado: um
    # cliente escrevendo o próprio "valor bruto" poderia inflar a informação
    # sem relação nenhuma com o que a retenção realmente deduziu.
    valor_bruto = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True, allow_null=True
    )
    # Declaração de que o valor digitado é bruto, para o lançamento avulso —
    # o único caminho que não tem fonte de renda de onde herdar isso. Sem ele,
    # uma receita CLT lançada avulsa entrava pelo valor do contracheque e
    # inflava o mês inteiro, porque INSS e IRPF nunca chegam à conta.
    valor_e_bruto = serializers.BooleanField(write_only=True, required=False, default=False)

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
            # Preenchido só quando houve retenção na fonte (CLT). A tela usa
            # isso para mostrar "R$ 24.000,00 brutos" ao lado do líquido —
            # sem isso o cliente vê um valor menor que o digitado e conclui
            # que a plataforma errou a conta.
            "valor_bruto",
            "valor_e_bruto",
            "ano",
            "mes",
            "fonte_renda",
            "fonte_renda_descricao",
            "regime",
            "regime_display",
            "tipo_renda",
            "tipo_renda_display",
            "despesa_recorrente",
            "recorrente",
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
        # Sai antes de qualquer caminho: é declaração de quem lança, não campo
        # do modelo, e sobra em `validated_data` estoura no `create`.
        e_bruto = attrs.pop("valor_e_bruto", False)

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

        # Avulso: sem fonte de onde herdar, quem declara que o valor é bruto é
        # quem está lançando. Só CLT tem retenção na fonte — em PJ e autônomo
        # o imposto é recolhido depois, e descontar aqui contaria duas vezes.
        if e_bruto and regime == RegimeTributario.CLT:
            bruto = self._valor_atual(attrs, "valor_realizado") or Decimal("0")
            if bruto > 0:
                household = self.context.get("household")
                retencao = calcular_retencao_clt(
                    Decimal(bruto), dependentes_do_household(household) if household else 0
                )
                attrs["valor_realizado"] = retencao.liquido
                attrs["valor_bruto"] = retencao.bruto if retencao.houve_retencao else None

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
