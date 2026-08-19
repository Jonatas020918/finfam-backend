from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.api import household_do_usuario

from .gateways import assinatura_do_household
from .models import DadosFiscais, Plan


class PlanoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = ["codigo", "nome", "preco_mensal", "preco_anual", "descricao"]
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
