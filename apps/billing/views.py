import logging

from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.api import household_do_usuario

from .gateways import assinatura_do_household, gateway_atual
from .models import DadosFiscais, Plan, StatusAssinatura

logger = logging.getLogger(__name__)


class PlanoSerializer(serializers.ModelSerializer):
    em_promocao = serializers.BooleanField(read_only=True)
    preco_de_entrada = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )

    class Meta:
        model = Plan
        fields = [
            "codigo",
            "nome",
            "descricao",
            "preco_mensal",
            "preco_promocional",
            "meses_promocionais",
            "preco_de_entrada",
            "em_promocao",
            "preco_anual",
            "recursos",
            "disponivel",
            "ordem",
        ]
        read_only_fields = fields


class DadosFiscaisSerializer(serializers.ModelSerializer):
    completo = serializers.BooleanField(read_only=True)

    class Meta:
        model = DadosFiscais
        fields = [
            "razao_social",
            "documento",
            "inscricao_municipal",
            "cep",
            "logradouro",
            "numero",
            "complemento",
            "bairro",
            "cidade",
            "uf",
            "completo",
        ]

    def validate_documento(self, valor):
        digitos = "".join(filtro for filtro in valor if filtro.isdigit())
        if len(digitos) not in (11, 14):
            raise serializers.ValidationError("Informe um CPF (11 dígitos) ou CNPJ (14 dígitos).")
        return digitos


class AssinaturaView(APIView):
    """GET /api/assinatura/ — estado da assinatura do núcleo familiar.

    A tela lê daqui para decidir o que mostrar: aviso de teste terminando,
    aviso de carência ou nada. Nenhuma dessas contas é refeita no cliente.
    """

    @extend_schema(responses={200: dict})
    def get(self, request):
        household = household_do_usuario(request.user)
        assinatura = assinatura_do_household(household) if household else None

        if assinatura is None:
            return Response({"possui_assinatura": False})

        return Response(
            {
                "possui_assinatura": True,
                "status": assinatura.status,
                "status_display": assinatura.get_status_display(),
                "da_acesso": assinatura.da_acesso,
                "em_teste": assinatura.em_teste,
                "em_carencia": assinatura.em_carencia,
                "dias_restantes": assinatura.dias_restantes,
                "motivo_do_bloqueio": assinatura.motivo_do_bloqueio,
                "trial_termina_em": assinatura.trial_termina_em,
                "carencia_ate": assinatura.carencia_ate,
                "proxima_cobranca": assinatura.proxima_cobranca,
                "periodicidade": assinatura.periodicidade,
                "plano": PlanoSerializer(assinatura.plano).data if assinatura.plano_id else None,
                # Enquanto não há gateway, a cobrança é combinada fora da
                # plataforma — a tela precisa saber para não oferecer checkout.
                "cobranca_automatica": bool(assinatura.gateway),
            }
        )


class PlanosView(APIView):
    """GET /api/planos/ — catálogo público de planos ativos."""

    permission_classes = []

    @extend_schema(responses={200: PlanoSerializer(many=True)})
    def get(self, request):
        planos = Plan.objects.filter(ativo=True).order_by("preco_mensal")
        return Response(PlanoSerializer(planos, many=True).data)


class CheckoutView(APIView):
    """POST /api/assinatura/checkout/ — abre o pagamento do plano escolhido.

    Recusa plano indisponível no servidor, e não só na interface: um plano
    marcado como "em breve" não pode ser assinado por quem chamar a API direto.
    """

    @extend_schema(request=dict, responses={200: dict})
    def post(self, request):
        codigo = request.data.get("plano")
        household = household_do_usuario(request.user)

        if household is None:
            raise NotFound("Usuário não possui núcleo familiar vinculado.")

        plano = Plan.objects.filter(codigo=codigo, ativo=True).first()
        if plano is None:
            raise NotFound("Plano não encontrado.")

        if not plano.disponivel:
            raise ValidationError(
                {"plano": f"O plano {plano.nome} ainda não está disponível para assinatura."}
            )

        assinatura = assinatura_do_household(household)
        if assinatura is None:
            raise NotFound("Não encontramos uma assinatura para esta conta.")

        # Quem já tem cobrança ativa no provedor não passa por aqui de novo: um
        # segundo checkout criaria uma segunda assinatura no Stripe, e o cliente
        # pagaria duas vezes pelo mesmo acesso. Troca de plano e de cartão é no
        # portal, que altera a assinatura existente em vez de criar outra.
        if assinatura.status == StatusAssinatura.ATIVA and assinatura.gateway_subscription_id:
            raise ValidationError(
                {
                    "plano": (
                        "Esta conta já tem uma assinatura ativa. Use o portal de "
                        "pagamento para trocar de plano ou atualizar o cartão."
                    )
                }
            )

        # O plano escolhido fica registrado antes do pagamento: se o cliente
        # abandonar o checkout, sabemos o que ele estava tentando comprar.
        assinatura.plano = plano
        assinatura.save(update_fields=["plano", "atualizado_em"])

        url_retorno = f"{settings.FRONTEND_URL.rstrip('/')}/assinatura"
        try:
            url = gateway_atual().criar_checkout(assinatura, plano, url_retorno)
        except (NotImplementedError, ValueError) as erro:
            raise ValidationError({"detail": str(erro)}) from erro

        return Response({"url": url, "plano": plano.codigo})


class PortalView(APIView):
    """POST /api/assinatura/portal/ — onde o cliente troca cartão e cancela."""

    @extend_schema(request=None, responses={200: dict})
    def post(self, request):
        household = household_do_usuario(request.user)
        assinatura = assinatura_do_household(household) if household else None
        if assinatura is None:
            raise NotFound("Não encontramos uma assinatura para esta conta.")

        url_retorno = f"{settings.FRONTEND_URL.rstrip('/')}/assinatura"
        try:
            url = gateway_atual().criar_portal(assinatura, url_retorno)
        except (NotImplementedError, ValueError) as erro:
            raise ValidationError({"detail": str(erro)}) from erro

        return Response({"url": url})


@method_decorator(csrf_exempt, name="dispatch")
class WebhookView(APIView):
    """POST /api/assinatura/webhook/ — eventos do provedor de pagamento.

    Público por necessidade: quem chama é o Stripe, não o navegador do cliente.
    A autenticidade vem da assinatura criptográfica do próprio evento — sem o
    segredo configurado, a rota recusa tudo, para não virar um endereço onde
    qualquer um libera acesso.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(request=None, responses={200: dict})
    def post(self, request):
        if not settings.STRIPE_WEBHOOK_SECRET:
            logger.warning("Webhook recebido sem STRIPE_WEBHOOK_SECRET configurado.")
            return Response(
                {"detail": "Webhook não configurado."}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        gateway = gateway_atual()
        assinatura_do_cabecalho = request.META.get("HTTP_STRIPE_SIGNATURE", "")

        try:
            evento = gateway._verificar_assinatura_do_evento(
                request.body, assinatura_do_cabecalho
            )
        except Exception as erro:
            logger.warning("Evento recusado na verificação de assinatura: %s", erro)
            return Response(
                {"detail": "Assinatura do evento inválida."}, status=status.HTTP_400_BAD_REQUEST
            )

        atualizada = gateway.processar_evento(evento)
        return Response({"processado": atualizada is not None})


class DadosFiscaisView(RetrieveUpdateAPIView):
    """Dados de faturamento, necessários para emitir a NFS-e."""

    serializer_class = DadosFiscaisSerializer

    def get_object(self):
        household = household_do_usuario(self.request.user)
        if household is None:
            from rest_framework.exceptions import NotFound

            raise NotFound("Usuário não possui núcleo familiar vinculado.")

        dados, _ = DadosFiscais.objects.get_or_create(
            household=household, defaults={"documento": ""}
        )
        return dados
