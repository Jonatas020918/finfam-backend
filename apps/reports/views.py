from datetime import date

from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.cashflow.models import CashFlowEntry
from apps.cashflow.services import historico_consolidado, resumo_mensal
from apps.common.api import HouseholdScopedMixin

from .pdf import gerar_extrato_mensal, gerar_historico_fluxo, gerar_retrato_financeiro
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


def _resposta_pdf(conteudo: bytes, nome_arquivo: str) -> HttpResponse:
    resposta = HttpResponse(conteudo, content_type="application/pdf")
    resposta["Content-Disposition"] = f'attachment; filename="{nome_arquivo}"'
    resposta["Content-Length"] = str(len(conteudo))
    return resposta


class RetratoFinanceiroPDFView(_HouseholdView):
    """GET /api/relatorios/retrato-financeiro/ — a mesma foto que o painel mostra."""

    @extend_schema(
        parameters=[OpenApiParameter("ano", int), OpenApiParameter("mes", int)],
        responses={(200, "application/pdf"): bytes},
    )
    def get(self, request):
        ano, mes = self._referencia(request)
        household = self.get_household()

        pdf = gerar_retrato_financeiro(montar_dashboard(household, ano, mes))
        return _resposta_pdf(pdf, f"retrato-financeiro-{ano}-{mes:02d}.pdf")


class ExtratoMensalPDFView(_HouseholdView):
    """GET /api/relatorios/extrato-mensal/ — receitas e despesas da competência.

    É o documento que o cliente leva ao contador: cada lançamento, sua origem
    (fixo ou variável) e o vínculo tributário das receitas.
    """

    @extend_schema(
        parameters=[OpenApiParameter("ano", int), OpenApiParameter("mes", int)],
        responses={(200, "application/pdf"): bytes},
    )
    def get(self, request):
        ano, mes = self._referencia(request)
        household = self.get_household()

        lancamentos = (
            CashFlowEntry.objects.filter(household=household, ano=ano, mes=mes)
            .select_related("membro")
            .order_by("tipo", "-valor_realizado")
        )

        pdf = gerar_extrato_mensal(
            household_nome=household.nome,
            ano=ano,
            mes=mes,
            resumo=resumo_mensal(household, ano, mes),
            lancamentos=lancamentos,
        )
        return _resposta_pdf(pdf, f"receitas-e-despesas-{ano}-{mes:02d}.pdf")


class HistoricoFluxoPDFView(_HouseholdView):
    """GET /api/relatorios/historico-fluxo/ — vários meses num documento só.

    O extrato mensal serve ao contador; este serve à decisão. Renda variável
    só se lê em série: um mês isolado não responde "quanto eu ganho", e a
    média sozinha esconde justamente o mês em que faltou.
    """

    @extend_schema(
        parameters=[
            OpenApiParameter("ano", int, description="Último mês do período. Padrão: hoje"),
            OpenApiParameter("mes", int),
            OpenApiParameter("meses", int, description="Quantos meses. Padrão: 12, máximo 36"),
        ],
        responses={(200, "application/pdf"): bytes},
    )
    def get(self, request):
        ano, mes = self._referencia(request)
        household = self.get_household()
        meses = int(request.query_params.get("meses", 12))

        historico = historico_consolidado(household, ano, mes, meses)
        pdf = gerar_historico_fluxo(household_nome=household.nome, historico=historico)
        return _resposta_pdf(pdf, f"fluxo-de-caixa-{meses}-meses-ate-{ano}-{mes:02d}.pdf")
