from datetime import date

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.api import HouseholdScopedMixin, household_do_usuario

from .competencia import abrir_competencia, competencias_com_movimento, propagar_alteracao
from .liquido import calcular_retencao_clt, dependentes_do_household, liquido_da_fonte
from .models import CashFlowEntry, RecurringExpense
from .serializers import (
    AbrirCompetenciaSerializer,
    CashFlowEntrySerializer,
    RecurringExpenseSerializer,
    ResumoMensalSerializer,
)
from .services import resumo_mensal


class RecurringExpenseViewSet(HouseholdScopedMixin, viewsets.ModelViewSet):
    """Despesas fixas: cadastro que se repete, não lançamento de um mês."""

    queryset = RecurringExpense.objects.select_related("membro", "divida").all()
    serializer_class = RecurringExpenseSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["household"] = self.get_household()
        return ctx

    def perform_update(self, serializer):
        """Alterar a despesa fixa reflete nos meses ainda em aberto."""
        valor_anterior = self.get_object().valor_previsto
        recorrente = serializer.save()

        propagar_alteracao(
            recorrente.lancamentos.all(),
            valor_anterior=valor_anterior,
            valor_novo=recorrente.valor_previsto,
            descricao_nova=recorrente.descricao,
            extras={"categoria": recorrente.categoria, "membro_id": recorrente.membro_id},
        )

    def perform_destroy(self, instance):
        """Remover o cadastro limpa os meses em aberto, preservando o passado."""
        limite = date.today().year * 12 + date.today().month
        for lancamento in instance.lancamentos.all():
            if lancamento.ano * 12 + lancamento.mes >= limite:
                lancamento.delete()
        instance.delete()


class AbrirCompetenciaView(HouseholdScopedMixin, APIView):
    """POST /api/competencias/abrir/ — materializa os itens fixos do mês.

    É POST, e não efeito colateral de um GET, porque cria dados. A tela chama ao
    abrir uma competência; chamar de novo não duplica nada nem sobrescreve valor
    que o usuário já tenha ajustado.
    """

    @extend_schema(request=AbrirCompetenciaSerializer, responses={200: dict})
    def post(self, request):
        serializer = AbrirCompetenciaSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dados = serializer.validated_data

        resultado = abrir_competencia(self.get_household(), dados["ano"], dados["mes"])
        return Response(
            {
                "ano": resultado.ano,
                "mes": resultado.mes,
                "criados": resultado.criados,
                "receitas_criadas": resultado.receitas_criadas,
                "despesas_criadas": resultado.despesas_criadas,
                "ja_existiam": resultado.ja_existiam,
            }
        )


class CompetenciasView(HouseholdScopedMixin, APIView):
    """GET /api/competencias/ — meses que já têm movimento, para o seletor."""

    @extend_schema(responses={200: dict})
    def get(self, request):
        return Response({"competencias": competencias_com_movimento(self.get_household())})


class CashFlowEntryViewSet(HouseholdScopedMixin, viewsets.ModelViewSet):
    queryset = CashFlowEntry.objects.select_related("membro").all()
    serializer_class = CashFlowEntrySerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["household"] = self.get_household()
        return ctx

    def get_queryset(self):
        qs = super().get_queryset()
        ano = self.request.query_params.get("ano")
        mes = self.request.query_params.get("mes")
        if ano:
            qs = qs.filter(ano=ano)
        if mes:
            qs = qs.filter(mes=mes)
        return qs

    @extend_schema(request=None, responses={200: CashFlowEntrySerializer})
    @action(detail=True, methods=["post"])
    def recalcular(self, request, pk=None):
        """Faz o lançamento voltar a seguir o cadastro da fonte.

        Ajustar um mês à mão é definitivo por desenho: a partir daí a
        propagação não toca mais nele, porque a correção de quem viveu o mês
        vale mais que a média cadastrada. O preço é que não havia caminho de
        volta — quem editou por engano, ou antes de marcar que o valor era
        bruto, ficava com o número errado para sempre e sem nada na tela que
        explicasse por quê.

        Só faz sentido em fonte fixa: na variável, o valor do mês é digitado
        e não existe no cadastro para ser recuperado.
        """
        lancamento = self.get_object()
        fonte = lancamento.fonte_renda

        if fonte is None:
            raise ValidationError(
                {
                    "detail": (
                        "Este lançamento não veio de uma fonte de renda cadastrada, "
                        "então não há cadastro de onde recalcular."
                    )
                }
            )
        if not fonte.fixa:
            raise ValidationError(
                {
                    "detail": (
                        "Esta fonte é variável: o valor de cada mês é informado por "
                        "você, e não fica guardado no cadastro para ser recuperado."
                    )
                }
            )

        valor = liquido_da_fonte(fonte)
        lancamento.valor_realizado = valor.liquido
        lancamento.valor_orcado = valor.liquido
        lancamento.valor_bruto = valor.bruto if valor.houve_retencao else None
        lancamento.descricao = fonte.descricao
        lancamento.regime = fonte.regime
        lancamento.tipo_renda = fonte.tipo
        lancamento.save(
            update_fields=[
                "valor_realizado", "valor_orcado", "valor_bruto",
                "descricao", "regime", "tipo_renda", "atualizado_em",
            ]
        )
        return Response(self.get_serializer(lancamento).data)

    @extend_schema(
        parameters=[
            OpenApiParameter("ano", int, description="Padrão: mês corrente"),
            OpenApiParameter("mes", int),
        ],
        responses={200: ResumoMensalSerializer},
    )
    @action(detail=False, methods=["get"])
    def resumo(self, request):
        hoje = date.today()
        ano = int(request.query_params.get("ano", hoje.year))
        mes = int(request.query_params.get("mes", hoje.month))
        dados = resumo_mensal(self.get_household(), ano, mes)
        return Response(ResumoMensalSerializer(dados).data)


class ValorBrutoSerializer(serializers.Serializer):
    valor_bruto = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)


class SimularLiquidoCltView(APIView):
    """GET /api/simuladores/liquido-clt/?valor_bruto=24000

    Prévia do desconto de INSS e IRPF enquanto a pessoa ainda está digitando
    o valor — antes de qualquer fonte de renda existir para consultar. Usa os
    dependentes já cadastrados no núcleo, a mesma regra que vale quando o
    lançamento é de fato materializado.

    Existe para que "quanto cai na conta" pare de ser uma surpresa só visível
    depois de salvar e abrir o mês: a pergunta que a pessoa faz no momento de
    digitar o número é respondida no mesmo instante.
    """

    @extend_schema(
        parameters=[OpenApiParameter("valor_bruto", float, required=True)],
        responses={200: dict},
    )
    def get(self, request):
        household = household_do_usuario(request.user)
        if household is None:
            raise NotFound("Usuário não possui núcleo familiar vinculado.")

        serializer = ValorBrutoSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        bruto = serializer.validated_data["valor_bruto"]

        resultado = calcular_retencao_clt(bruto, dependentes_do_household(household))
        return Response(
            {
                "bruto": str(resultado.bruto),
                "liquido": str(resultado.liquido),
                "retido": str(resultado.retido),
            }
        )
