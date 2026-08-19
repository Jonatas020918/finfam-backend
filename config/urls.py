from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter

from apps.billing.views import (
    AssinaturaView,
    CheckoutView,
    DadosFiscaisView,
    PlanosView,
    PortalView,
    WebhookView,
)
from apps.cashflow.views import (
    AbrirCompetenciaView,
    CashFlowEntryViewSet,
    CompetenciasView,
    RecurringExpenseViewSet,
)
from apps.education.views import EducationalReportViewSet, IndicadoresView
from apps.goals.views import GoalViewSet
from apps.households.views import (
    AssetViewSet,
    ConcluirOnboardingView,
    DebtViewSet,
    IncomeSourceViewSet,
    LifeGoalViewSet,
    MemberViewSet,
    MeuHouseholdView,
)
from apps.reports.views import (
    DashboardView,
    ExtratoMensalPDFView,
    RetratoFinanceiroPDFView,
)
from apps.simulators.views import (
    AmortizacaoView,
    BaseRealParaSimulacaoView,
    CompararRegimesView,
    ProjecaoView,
    SimulationRunViewSet,
)

router = DefaultRouter()
router.register("membros", MemberViewSet, basename="membro")
router.register("fontes-renda", IncomeSourceViewSet, basename="fonte-renda")
router.register("patrimonios", AssetViewSet, basename="patrimonio")
router.register("dividas", DebtViewSet, basename="divida")
router.register("objetivos", LifeGoalViewSet, basename="objetivo")
router.register("lancamentos", CashFlowEntryViewSet, basename="lancamento")
router.register("despesas-fixas", RecurringExpenseViewSet, basename="despesa-fixa")
router.register("metas", GoalViewSet, basename="meta")
router.register("simulacoes", SimulationRunViewSet, basename="simulacao")
router.register("relatorios-educacionais", EducationalReportViewSet, basename="relatorio-educacional")

@api_view(["GET"])
@permission_classes([AllowAny])
def saude(_request):
    """Sonda de saúde do container: precisa ser pública e barata."""
    return Response({"status": "ok"})


api_urlpatterns = [
    path("saude/", saude, name="saude"),
    path("", include("apps.accounts.urls")),
    path("nucleo-familiar/", MeuHouseholdView.as_view(), name="meu-household"),
    path(
        "nucleo-familiar/concluir-onboarding/",
        ConcluirOnboardingView.as_view(),
        name="concluir-onboarding",
    ),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("competencias/", CompetenciasView.as_view(), name="competencias"),
    path("competencias/abrir/", AbrirCompetenciaView.as_view(), name="abrir-competencia"),
    path("indicadores/", IndicadoresView.as_view(), name="indicadores"),
    path("assinatura/", AssinaturaView.as_view(), name="assinatura"),
    path("assinatura/dados-fiscais/", DadosFiscaisView.as_view(), name="dados-fiscais"),
    path("planos/", PlanosView.as_view(), name="planos"),
    path("assinatura/checkout/", CheckoutView.as_view(), name="checkout"),
    path("assinatura/portal/", PortalView.as_view(), name="portal-assinatura"),
    path("assinatura/webhook/", WebhookView.as_view(), name="webhook-assinatura"),
    path("simuladores/pj-clt/", CompararRegimesView.as_view(), name="simulador-pj-clt"),
    path(
        "simuladores/base-real/",
        BaseRealParaSimulacaoView.as_view(),
        name="simulador-base-real",
    ),
    path("simuladores/amortizacao/", AmortizacaoView.as_view(), name="simulador-amortizacao"),
    path("simuladores/projecao/", ProjecaoView.as_view(), name="simulador-projecao"),
    path(
        "relatorios/retrato-financeiro/",
        RetratoFinanceiroPDFView.as_view(),
        name="retrato-financeiro",
    ),
    path(
        "relatorios/extrato-mensal/",
        ExtratoMensalPDFView.as_view(),
        name="extrato-mensal",
    ),
    path("", include(router.urls)),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(api_urlpatterns)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]
