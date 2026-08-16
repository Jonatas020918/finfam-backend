from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.api import HouseholdScopedMixin, household_do_usuario

from .models import SimulationRun
from .rules import VERSAO_REGRAS
from .serializers import EntradaSimulacaoSerializer, SimulationRunSerializer
from .services import EntradaSimulacao, comparar_regimes


class CompararRegimesView(APIView):
    """POST /api/simuladores/pj-clt/ — compara os três regimes com a mesma entrada."""

    @extend_schema(request=EntradaSimulacaoSerializer, responses={200: dict})
    def post(self, request):
        serializer = EntradaSimulacaoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dados = dict(serializer.validated_data)
        salvar = dados.pop("salvar", False)
        membro_id = dados.pop("membro", None)

        entrada = EntradaSimulacao(**dados)
        resultado = comparar_regimes(entrada)

        if salvar:
            household = household_do_usuario(request.user)
            if household is not None:
                membro = None
                if membro_id:
                    membro = household.membros.filter(pk=membro_id).first()
                SimulationRun.objects.create(
                    tenant=household.tenant,
                    household=household,
                    membro=membro,
                    entrada=resultado["entrada"],
                    resultado=resultado,
                    versao_regras=VERSAO_REGRAS,
                )
        return Response(resultado)


class SimulationRunViewSet(
    HouseholdScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Histórico de simulações salvas do núcleo familiar."""

    queryset = SimulationRun.objects.all()
    serializer_class = SimulationRunSerializer
