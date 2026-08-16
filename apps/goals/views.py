from rest_framework import viewsets

from apps.common.api import HouseholdScopedMixin

from .models import Goal
from .serializers import GoalSerializer


class GoalViewSet(HouseholdScopedMixin, viewsets.ModelViewSet):
    queryset = Goal.objects.select_related("membro", "objetivo").all()
    serializer_class = GoalSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["household"] = self.get_household()
        return ctx
