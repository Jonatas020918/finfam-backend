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


class HouseholdScopedMixin:
    """Restringe qualquer queryset ao núcleo familiar do usuário autenticado.

    É a barreira de isolamento da seção 2.4: nenhum endpoint de cliente enxerga
    dados de outro núcleo, e o filtro por `tenant` é aplicado junto para que um
    vazamento exija duas falhas simultâneas, não uma.
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


class IsCliente(permissions.BasePermission):
    message = "Disponível apenas para usuários com perfil de cliente."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)
