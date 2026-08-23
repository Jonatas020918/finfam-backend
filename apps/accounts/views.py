import json
import logging

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User
from .senha import solicitar_redefinicao, usuario_do_token
from .serializers import (
    ConfirmarRedefinicaoSerializer,
    GoogleAuthSerializer,
    SignupSerializer,
    SolicitarRedefinicaoSerializer,
    UserSerializer,
)
from .services import provisionar_conta
from .utils import ip_da_requisicao

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


class GoogleAuthView(APIView):
    """POST /api/auth/google/ — entra ou cadastra usando a conta Google.

    O token vem pronto do botão do Google e é verificado aqui contra as
    chaves públicas do próprio Google — a assinatura garante que ninguém
    forjou um e-mail alheio, sem precisar de segredo compartilhado nenhum.

    Conta nova aqui nasce **sem** aceite dos termos: "entrar com o Google" e
    "concordar com os termos de uso" são coisas diferentes, e misturar as
    duas transformaria um clique de login em consentimento por omissão. A
    tela é quem decide o que fazer com `termos_aceitos=False` na resposta —
    hoje, mandar para a tela de aceite antes de liberar o resto.
    """

    permission_classes = [permissions.AllowAny]

    @extend_schema(request=GoogleAuthSerializer, responses={200: UserSerializer})
    def post(self, request):
        serializer = GoogleAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            claims = google_id_token.verify_oauth2_token(
                serializer.validated_data["credential"],
                google_requests.Request(),
                settings.GOOGLE_OAUTH_CLIENT_ID,
            )
        except ValueError as erro:
            raise ValidationError(
                {"credential": "Não foi possível confirmar sua conta Google. Tente de novo."}
            ) from erro

        if not claims.get("email_verified"):
            raise ValidationError(
                {"credential": "O e-mail da sua conta Google ainda não foi verificado."}
            )

        email = claims["email"].lower()
        google_sub = claims["sub"]

        user = User.objects.filter(email=email).first()
        criado = False
        if user is None:
            user = provisionar_conta(
                email=email,
                nome_completo=claims.get("name") or email.split("@")[0],
                password=None,
                google_sub=google_sub,
            )
            criado = True
        elif not user.google_sub:
            # Conta já existia (cadastro por senha) e está usando o Google
            # pela primeira vez — só liga as duas, não mexe em mais nada.
            user.google_sub = google_sub
            user.save(update_fields=["google_sub", "atualizado_em"])

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "user": UserSerializer(user).data,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "criado": criado,
            },
            status=status.HTTP_201_CREATED if criado else status.HTTP_200_OK,
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


class ExportarDadosView(APIView):
    """GET /api/me/exportar-dados/ — direito de acesso (LGPD, art. 18, II).

    Devolve um arquivo, e não um JSON na tela, porque o titular precisa
    **guardar** isso. Um corpo de resposta que só aparece no navegador atende à
    letra da lei e não ao propósito dela.
    """

    @extend_schema(responses={200: dict})
    def get(self, request):
        from apps.common.api import household_do_usuario

        from .lgpd import exportar

        household = household_do_usuario(request.user)
        if household is None:
            raise NotFound("Usuário não possui núcleo familiar vinculado.")

        dados = exportar(household, request.user)
        conteudo = json.dumps(dados, ensure_ascii=False, indent=2)

        resposta = HttpResponse(conteudo, content_type="application/json; charset=utf-8")
        carimbo = timezone.now().strftime("%Y-%m-%d")
        resposta["Content-Disposition"] = (
            f'attachment; filename="batimento-meus-dados-{carimbo}.json"'
        )
        return resposta


class ExcluirContaView(APIView):
    """DELETE /api/me/ — direito de eliminação (LGPD, art. 18, VI).

    Exige a senha no corpo. Não é burocracia: a ação é irreversível e apaga
    anos de histórico financeiro. Um clique acidental — ou um navegador aberto
    numa mesa alheia — não pode bastar.
    """

    @extend_schema(request=dict, responses={200: dict})
    def delete(self, request):
        from .lgpd import excluir_conta

        senha = request.data.get("senha") or ""
        if not request.user.check_password(senha):
            raise ValidationError(
                {"senha": "Senha incorreta. A exclusão não foi realizada."}
            )

        email = request.user.email
        resultado = excluir_conta(request.user)
        logger.info("Conta excluída a pedido do titular: %s", email)

        return Response(
            {
                "excluida": True,
                "registros_apagados": resultado.registros_apagados,
                "detalhe": (
                    "Seus dados foram eliminados. Mantivemos apenas o registro de "
                    "cobrança exigido pela legislação fiscal, sem nenhuma informação "
                    "que identifique você."
                ),
            }
        )


class TermosView(APIView):
    """GET /api/termos/ — a versão em vigor e o contato do encarregado."""

    permission_classes = [permissions.AllowAny]

    @extend_schema(responses={200: dict})
    def get(self, request):
        return Response(
            {
                "versao": settings.VERSAO_TERMOS,
                "encarregado_email": settings.ENCARREGADO_DADOS_EMAIL,
            }
        )


class AceitarTermosView(APIView):
    """POST /api/me/aceitar-termos/ — registra o aceite da versão em vigor."""

    @extend_schema(request=None, responses={200: UserSerializer})
    def post(self, request):
        request.user.aceite_termos_versao = settings.VERSAO_TERMOS
        request.user.aceite_termos_em = timezone.now()
        request.user.aceite_termos_ip = ip_da_requisicao(request)
        request.user.save(
            update_fields=[
                "aceite_termos_versao",
                "aceite_termos_em",
                "aceite_termos_ip",
                "atualizado_em",
            ]
        )
        return Response(UserSerializer(request.user).data)
