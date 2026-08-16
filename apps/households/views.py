from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.api import HouseholdScopedMixin

from .models import Asset, Debt, Household, IncomeSource, LifeGoal, Member
from .serializers import (
    AssetSerializer,
    DebtSerializer,
    HouseholdSerializer,
    IncomeSourceSerializer,
    LifeGoalSerializer,
    MemberSerializer,
)


class MeuHouseholdView(RetrieveUpdateAPIView):
    """Dados do próprio núcleo familiar — não existe listagem de households."""

    serializer_class = HouseholdSerializer

    def get_object(self):
        membro = getattr(self.request.user, "membro", None)
        if membro is None:
            from rest_framework.exceptions import NotFound

            raise NotFound("Usuário não possui núcleo familiar vinculado.")
        return (
            Household.objects.filter(pk=membro.household_id)
            .prefetch_related("membros")
            .get()
        )


class ConcluirOnboardingView(APIView):
    """Marca o onboarding como concluído e libera o dashboard."""

    @extend_schema(request=None, responses={200: HouseholdSerializer})
    def post(self, request, *args, **kwargs):
        membro = getattr(request.user, "membro", None)
        if membro is None:
            return Response(
                {"detail": "Usuário não possui núcleo familiar vinculado."},
                status=status.HTTP_404_NOT_FOUND,
            )
        household = membro.household
        household.onboarding_concluido_em = timezone.now()
        household.save(update_fields=["onboarding_concluido_em", "atualizado_em"])
        return Response(HouseholdSerializer(household).data)


class _ScopedViewSet(HouseholdScopedMixin, viewsets.ModelViewSet):
    """Base dos recursos filhos do núcleo familiar."""

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["household"] = self.get_household()
        return ctx


class MemberViewSet(_ScopedViewSet):
    queryset = Member.objects.select_related("usuario").all()
    serializer_class = MemberSerializer


class IncomeSourceViewSet(_ScopedViewSet):
    queryset = IncomeSource.objects.select_related("membro").all()
    serializer_class = IncomeSourceSerializer


class AssetViewSet(_ScopedViewSet):
    queryset = Asset.objects.select_related("membro").all()
    serializer_class = AssetSerializer


class DebtViewSet(_ScopedViewSet):
    queryset = Debt.objects.select_related("membro").all()
    serializer_class = DebtSerializer


class LifeGoalViewSet(_ScopedViewSet):
    queryset = LifeGoal.objects.select_related("membro").all()
    serializer_class = LifeGoalSerializer
