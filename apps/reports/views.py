from datetime import date

from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.api import HouseholdScopedMixin

from .pdf import gerar_pdf, renderizar_html
from .services import montar_dashboard


class _HouseholdView(HouseholdScopedMixin, APIView):
    def _referencia(self, request) -> tuple[int, int]:
        hoje = date.today()
        return (
            int(request.query_params.get("ano", hoje.year)),
            int(request.query_params.get("mes", hoje.month)),
        )


class DashboardView(_HouseholdView):
    """GET /api/dashboard/ — payload único da tela principal do cliente."""

    @extend_schema(
        parameters=[OpenApiParameter("ano", int), OpenApiParameter("mes", int)],
        responses={200: dict},
    )
    def get(self, request):
        ano, mes = self._referencia(request)
        return Response(montar_dashboard(self.get_household(), ano, mes))


class RetratoFinanceiroPDFView(_HouseholdView):
    """GET /api/relatorios/retrato-financeiro.pdf — retrato sob demanda."""

    def get(self, request):
        ano, mes = self._referencia(request)
        household = self.get_household()
        contexto = {
            "dashboard": montar_dashboard(household, ano, mes),
            "gerado_em": date.today(),
            "anotacoes": None,  # preenchido no modo consultoria (Fase 2)
        }

        if request.query_params.get("formato") == "html":
            # Útil para revisar o layout sem depender do WeasyPrint instalado.
            return HttpResponse(renderizar_html(contexto))

        pdf = gerar_pdf(contexto)
        resposta = HttpResponse(pdf, content_type="application/pdf")
        nome = f"retrato-financeiro-{mes:02d}-{ano}.pdf"
        resposta["Content-Disposition"] = f'attachment; filename="{nome}"'
        return resposta
