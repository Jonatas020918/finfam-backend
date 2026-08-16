from django.db.models import Q
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.serializers import ModelSerializer

from .models import EducationalReport, StatusRelatorio


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
