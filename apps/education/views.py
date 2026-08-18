from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.serializers import BooleanField, ModelSerializer
from rest_framework.views import APIView

from .models import EducationalReport, IndicadorMensal, StatusRelatorio


class EducationalReportSerializer(ModelSerializer):
    class Meta:
        model = EducationalReport
        fields = [
            "id",
            "ano",
            "mes",
            "titulo",
            "selic_meta_percentual",
            "selic_variacao_mes",
            "ipca_mes_percentual",
            "ipca_12m_percentual",
            "fonte_dados",
            "secoes",
            "glossario",
            "disclaimer",
            "publicado_em",
        ]
        read_only_fields = fields


class IndicadorMensalSerializer(ModelSerializer):
    completo = BooleanField(read_only=True)

    class Meta:
        model = IndicadorMensal
        fields = [
            "ano",
            "mes",
            "selic_meta_percentual",
            "selic_variacao_mes",
            "ipca_mes_percentual",
            "ipca_12m_percentual",
            "fonte",
            "sincronizado_em",
            "completo",
        ]
        read_only_fields = fields


class IndicadoresView(APIView):
    """GET /api/indicadores/ — Selic e IPCA oficiais, sempre atualizados.

    Independe do relatório educacional: os números são públicos e vão ao ar
    assim que o job diário os coleta, sem passar por revisão editorial.
    """

    @extend_schema(
        parameters=[OpenApiParameter("meses", int, description="Histórico a retornar (padrão 12)")],
        responses={200: dict},
    )
    def get(self, request):
        meses = min(int(request.query_params.get("meses", 12)), 60)
        historico = IndicadorMensal.objects.all()[:meses]

        return Response(
            {
                "atuais": IndicadorMensal.mais_recentes(),
                "fonte": "Banco Central do Brasil — Sistema Gerenciador de Séries Temporais",
                "series_utilizadas": {
                    "selic_meta": 432,
                    "ipca_mensal": 433,
                    "ipca_12_meses": 13522,
                },
                # Do mais antigo para o mais recente: é a ordem que o gráfico espera.
                "historico": IndicadorMensalSerializer(
                    sorted(historico, key=lambda i: (i.ano, i.mes)), many=True
                ).data,
            }
        )


class EducationalReportViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Relatórios educacionais visíveis ao cliente.

    Só expõe o que já passou por revisão humana — rascunhos ficam restritos ao
    admin do Django.
    """

    serializer_class = EducationalReportSerializer

    def get_queryset(self):
        tenant_id = getattr(self.request.user, "tenant_id", None)
        # Relatório global (tenant nulo) + relatórios do próprio tenant.
        return EducationalReport.objects.filter(
            Q(status=StatusRelatorio.PUBLICADO),
            Q(tenant__isnull=True) | Q(tenant_id=tenant_id),
        )

    @action(detail=False, methods=["get"])
    def atual(self, request):
        """Último relatório publicado — é o que o dashboard resume."""
        relatorio = self.get_queryset().order_by("-ano", "-mes").first()
        if relatorio is None:
            return Response({"detail": "Nenhum relatório publicado ainda."}, status=404)
        return Response(self.get_serializer(relatorio).data)
