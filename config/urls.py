from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from apps.cashflow.views import CashFlowEntryViewSet
from apps.education.views import EducationalReportViewSet
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
from apps.reports.views import DashboardView, RetratoFinanceiroPDFView
from apps.simulators.views import (
    BaseRealParaSimulacaoView,
    CompararRegimesView,
    SimulationRunViewSet,
)

router = DefaultRouter()
router.register("membros", MemberViewSet, basename="membro")
router.register("fontes-renda", IncomeSourceViewSet, basename="fonte-renda")
router.register("patrimonios", AssetViewSet, basename="patrimonio")
router.register("dividas", DebtViewSet, basename="divida")
router.register("objetivos", LifeGoalViewSet, basename="objetivo")
router.register("lancamentos", CashFlowEntryViewSet, basename="lancamento")
router.register("metas", GoalViewSet, basename="meta")
router.register("simulacoes", SimulationRunViewSet, basename="simulacao")
router.register("relatorios-educacionais", EducationalReportViewSet, basename="relatorio-educacional")

api_urlpatterns = [
    path("", include("apps.accounts.urls")),
    path("nucleo-familiar/", MeuHouseholdView.as_view(), name="meu-household"),
    path(
        "nucleo-familiar/concluir-onboarding/",
        ConcluirOnboardingView.as_view(),
        name="concluir-onboarding",
    ),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("simuladores/pj-clt/", CompararRegimesView.as_view(), name="simulador-pj-clt"),
    path(
        "simuladores/base-real/",
        BaseRealParaSimulacaoView.as_view(),
        name="simulador-base-real",
    ),
    path(
        "relatorios/retrato-financeiro/",
        RetratoFinanceiroPDFView.as_view(),
        name="retrato-financeiro",
    ),
    path("", include(router.urls)),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(api_urlpatterns)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]
