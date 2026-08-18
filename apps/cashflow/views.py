from datetime import date

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.api import HouseholdScopedMixin

from .competencia import abrir_competencia, competencias_com_movimento
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
