from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import SignupSerializer, UserSerializer


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


class AceitarDisclaimerView(APIView):
    """Aceite do disclaimer do módulo educacional (seção 3.6)."""

    @extend_schema(request=None, responses={200: UserSerializer})
    def post(self, request):
        request.user.aceite_disclaimer_educacional_em = timezone.now()
        request.user.save(update_fields=["aceite_disclaimer_educacional_em", "atualizado_em"])
        return Response(UserSerializer(request.user).data)
