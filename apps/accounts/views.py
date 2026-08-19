import logging

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .senha import solicitar_redefinicao, usuario_do_token
from .serializers import (
    ConfirmarRedefinicaoSerializer,
    SignupSerializer,
    SolicitarRedefinicaoSerializer,
    UserSerializer,
)

logger = logging.getLogger(__name__)


class SignupView(generics.CreateAPIView):
    """Cadastro self-service. Devolve o par de tokens já autenticado."""

    serializer_class = SignupSerializer
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses={201: UserSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "user": UserSerializer(user).data,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            status=status.HTTP_201_CREATED,
        )


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class SolicitarRedefinicaoView(APIView):
    """POST /api/auth/esqueci-senha/ — dispara o e-mail com o link.

    Responde sempre 200 com a mesma mensagem, exista ou não a conta: informar o
    contrário transformaria o endpoint em uma lista de clientes consultável.
    """

    permission_classes = [permissions.AllowAny]
    throttle_scope = "redefinicao_senha"

    @extend_schema(request=SolicitarRedefinicaoSerializer, responses={200: dict})
    def post(self, request):
        serializer = SolicitarRedefinicaoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            solicitar_redefinicao(serializer.validated_data["email"])
        except Exception:
            # Falha de SMTP não pode virar sinal de que a conta existe.
            logger.exception("Falha ao enviar e-mail de redefinição de senha")

        return Response(
            {
                "detail": (
                    "Se houver uma conta com este e-mail, enviamos um link para "
                    "redefinir a senha. Confira também a caixa de spam."
                )
            }
        )


class ConfirmarRedefinicaoView(APIView):
    """POST /api/auth/nova-senha/ — troca a senha usando o link recebido."""

    permission_classes = [permissions.AllowAny]
    throttle_scope = "redefinicao_senha"

    @extend_schema(request=ConfirmarRedefinicaoSerializer, responses={200: dict})
    def post(self, request):
        serializer = ConfirmarRedefinicaoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dados = serializer.validated_data

        user = usuario_do_token(dados["uid"], dados["token"])
        if user is None:
            return Response(
                {
                    "detail": (
                        "Este link é inválido ou já expirou. Peça um novo na tela de acesso."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(dados["password"])
        user.save(update_fields=["password", "atualizado_em"])
        # Trocar a senha invalida o token: ele é derivado do hash anterior.
        return Response({"detail": "Senha alterada. Você já pode entrar com ela."})


class AceitarDisclaimerView(APIView):
    """Aceite do disclaimer do módulo educacional (seção 3.6)."""

    @extend_schema(request=None, responses={200: UserSerializer})
    def post(self, request):
        request.user.aceite_disclaimer_educacional_em = timezone.now()
        request.user.save(update_fields=["aceite_disclaimer_educacional_em", "atualizado_em"])
        return Response(UserSerializer(request.user).data)
