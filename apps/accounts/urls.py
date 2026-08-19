from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenVerifyView

from .views import (
    AceitarDisclaimerView,
    ConfirmarRedefinicaoView,
    MeView,
    SignupView,
    SolicitarRedefinicaoView,
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
]
