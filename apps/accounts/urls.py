from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenVerifyView

from .views import (
    AceitarDisclaimerView,
    AceitarTermosView,
    ConfirmarRedefinicaoView,
    ExcluirContaView,
    ExportarDadosView,
    MeView,
    SignupView,
    SolicitarRedefinicaoView,
    TermosView,
)

urlpatterns = [
    path("auth/signup/", SignupView.as_view(), name="signup"),
    path("auth/login/", TokenObtainPairView.as_view(), name="login"),
    path("auth/esqueci-senha/", SolicitarRedefinicaoView.as_view(), name="esqueci-senha"),
    path("auth/nova-senha/", ConfirmarRedefinicaoView.as_view(), name="nova-senha"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("auth/verify/", TokenVerifyView.as_view(), name="token-verify"),
    path("me/", MeView.as_view(), name="me"),
    path("me/aceitar-disclaimer/", AceitarDisclaimerView.as_view(), name="aceitar-disclaimer"),
    # --- LGPD: direitos do titular ----------------------------------------
    path("termos/", TermosView.as_view(), name="termos"),
    path("me/aceitar-termos/", AceitarTermosView.as_view(), name="aceitar-termos"),
    path("me/exportar-dados/", ExportarDadosView.as_view(), name="exportar-dados"),
    path("me/excluir-conta/", ExcluirContaView.as_view(), name="excluir-conta"),
]
