"""Peças compartilhadas da API: escopo por tenant/núcleo familiar."""

from rest_framework import permissions
from rest_framework.exceptions import NotFound


def household_do_usuario(user):
    """Núcleo familiar ao qual o usuário logado pertence.

    No MVP (self-service) o vínculo é sempre via `Member.usuario` — titular ou
    cônjuge com login próprio. Consultores (Fase 2) acessam por outro caminho,
    explicitamente escolhendo o cliente da carteira.
    """
    membro = getattr(user, "membro", None)
    return membro.household if membro else None


class ExigeAssinaturaMixin:
    """Telas que só fazem sentido com assinatura válida.

    Fica fora daqui, de propósito: autenticação, estado da assinatura e dados do
    usuário — quem está bloqueado precisa conseguir entrar, entender o motivo e
    resolver. Bloquear o login de quem deixou o cartão vencer é como trancar o
    cliente do lado de fora da loja onde ele quer pagar.
    """

    def get_permissions(self):
        from apps.billing.permissions import AssinaturaAtiva

        return [*super().get_permissions(), AssinaturaAtiva()]


class EscopoDoHouseholdMixin:
    """Isolamento por núcleo familiar, sem falar de assinatura.

    Separado de `HouseholdScopedMixin` porque as duas coisas são
    independentes: isolar dados é segurança e vale sempre; exigir assinatura é
    regra comercial e tem exceções. O onboarding é a exceção — a pessoa
    precisa cadastrar família e objetivos *antes* de escolher o plano, então
    esses recursos usam este mixin e ficam fora da cobrança.

    Quem for criar recurso novo: o padrão é `HouseholdScopedMixin`, logo
    abaixo. Use este aqui só se a tela precisar funcionar antes de existir
    assinatura, e saiba que está abrindo um buraco no bloqueio.
    """

    def get_household(self):
        household = household_do_usuario(self.request.user)
        if household is None:
            raise NotFound("Usuário não possui núcleo familiar vinculado.")
        return household

    def get_queryset(self):
        household = self.get_household()
        return (
            super()
            .get_queryset()
            .filter(household=household, tenant_id=household.tenant_id)
        )

    def perform_create(self, serializer):
        household = self.get_household()
        serializer.save(household=household, tenant=household.tenant)


class HouseholdScopedMixin(ExigeAssinaturaMixin, EscopoDoHouseholdMixin):
    """O padrão: isolado por núcleo familiar **e** atrás da assinatura.

    É a barreira de isolamento da seção 2.4: nenhum endpoint de cliente enxerga
    dados de outro núcleo, e o filtro por `tenant` é aplicado junto para que um
    vazamento exija duas falhas simultâneas, não uma.
    """


class IsCliente(permissions.BasePermission):
    message = "Disponível apenas para usuários com perfil de cliente."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)
