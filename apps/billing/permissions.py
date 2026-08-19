"""Bloqueio por assinatura.

Aplicado às telas que só fazem sentido pagando. Fica de fora, de propósito:
autenticação, o próprio estado da assinatura e os dados do usuário — quem está
bloqueado ainda precisa conseguir entrar, entender por quê e resolver.
"""

from rest_framework.exceptions import APIException

from apps.common.api import household_do_usuario

from .gateways import assinatura_do_household


class AssinaturaInativa(APIException):
    """402 é mais preciso que 403: não é falta de permissão, é falta de pagamento."""

    status_code = 402
    default_code = "assinatura_inativa"
    default_detail = "Sua assinatura não está ativa."


class AssinaturaAtiva:
    """Permite o acesso enquanto o teste, a assinatura ou a carência valerem."""

    message = "Assinatura inativa."

    def has_permission(self, request, view):
        household = household_do_usuario(request.user)
        if household is None:
            # Sem núcleo familiar não há o que cobrar; outras camadas tratam.
            return True

        assinatura = assinatura_do_household(household)
        if assinatura is None:
            raise AssinaturaInativa(
                "Não encontramos uma assinatura para a sua conta. Fale com o suporte."
            )

        if not assinatura.da_acesso:
            raise AssinaturaInativa(assinatura.motivo_do_bloqueio)

        return True

    def has_object_permission(self, request, view, obj):
        return True
