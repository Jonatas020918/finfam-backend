from datetime import date

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.common.api import HouseholdScopedMixin

from .models import CashFlowEntry
from .serializers import CashFlowEntrySerializer, ResumoMensalSerializer
from .services import resumo_mensal


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
