from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.cashflow.competencia import propagar_alteracao
from apps.cashflow.lancamento_mensal import historico_da_fonte, registrar_competencia
from apps.cashflow.liquido import liquido_da_fonte
from apps.cashflow.parcelas import sincronizar_despesa
from apps.common.api import HouseholdScopedMixin

from .models import Asset, Debt, Household, IncomeSource, LifeGoal, Member
from .serializers import (
    AssetSerializer,
    DebtSerializer,
    HouseholdSerializer,
    IncomeSourceSerializer,
    LancamentoCompetenciaSerializer,
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

    def perform_update(self, serializer):
        """Mudou o cadastro, mudam os meses em aberto que ainda o refletiam."""
        anterior = self.get_object()
        # A comparação e o novo valor são ambos em líquido — é isso que está
        # gravado nos lançamentos. Misturar bruto e líquido aqui faria a
        # propagação achar que o usuário editou o mês à mão e não atualizar
        # nada, silenciosamente.
        liquido_anterior = liquido_da_fonte(anterior).liquido
        fonte = serializer.save()
        valor = liquido_da_fonte(fonte)

        if fonte.fixa:
            propagar_alteracao(
                fonte.lancamentos.all(),
                valor_anterior=liquido_anterior,
                valor_novo=valor.liquido,
                descricao_nova=fonte.descricao,
                extras={
                    "regime": fonte.regime,
                    "tipo_renda": fonte.tipo,
                    "membro_id": fonte.membro_id,
                    "valor_bruto": valor.bruto if valor.houve_retencao else None,
                },
            )
        else:
            # Variável: o valor de cada mês é do usuário, mas a classificação
            # tributária precisa acompanhar — é ela que alimenta o simulador.
            propagar_alteracao(
                fonte.lancamentos.all(),
                valor_anterior=valor.liquido,
                valor_novo=valor.liquido,
                descricao_nova=fonte.descricao,
                extras={
                    "regime": fonte.regime,
                    "tipo_renda": fonte.tipo,
                    "membro_id": fonte.membro_id,
                },
            )

    @extend_schema(
        request=LancamentoCompetenciaSerializer,
        responses={200: dict},
        description="Registra (ou corrige) quanto esta fonte rendeu em uma competência.",
    )
    @action(detail=True, methods=["post"], url_path="competencia")
    def competencia(self, request, pk=None):
        fonte = self.get_object()
        serializer = LancamentoCompetenciaSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dados = serializer.validated_data

        lancamento, criado = registrar_competencia(
            fonte, dados["ano"], dados["mes"], dados["valor_realizado"]
        )
        return Response(
            {
                "lancamento_id": str(lancamento.id),
                "ano": lancamento.ano,
                "mes": lancamento.mes,
                "valor_realizado": lancamento.valor_realizado,
                "criado": criado,
            },
            status=status.HTTP_201_CREATED if criado else status.HTTP_200_OK,
        )

    @extend_schema(
        parameters=[OpenApiParameter("meses", int, description="Padrão: 12")],
        responses={200: dict},
    )
    @action(detail=True, methods=["get"])
    def historico(self, request, pk=None):
        fonte = self.get_object()
        meses = int(request.query_params.get("meses", 12))
        return Response(
            {
                "fonte_id": str(fonte.id),
                "descricao": fonte.descricao,
                "modo_lancamento": fonte.modo_lancamento,
                "media_realizada": fonte.media_realizada(meses),
                "competencias": historico_da_fonte(fonte, meses),
            }
        )


class AssetViewSet(_ScopedViewSet):
    queryset = Asset.objects.select_related("membro").all()
    serializer_class = AssetSerializer


class DebtViewSet(_ScopedViewSet):
    """Dívidas, e as parcelas que elas geram no orçamento.

    Cadastrar um financiamento cria também a despesa fixa da parcela. São duas
    coisas distintas — o saldo devedor alimenta a simulação de quitação, a
    parcela sai da conta todo mês — e sem a segunda o fluxo de caixa esconde a
    maior saída fixa da família.
    """

    queryset = Debt.objects.select_related("membro").all()
    serializer_class = DebtSerializer

    def perform_create(self, serializer):
        super().perform_create(serializer)
        sincronizar_despesa(serializer.instance)

    def perform_update(self, serializer):
        """Mexer na parcela aqui move a despesa junto: é o mesmo compromisso."""
        divida = serializer.save()
        sincronizar_despesa(divida)

    def perform_destroy(self, instance):
        """Apagar a dívida apaga a parcela dela do orçamento.

        Explícito porque o vínculo é `SET_NULL`: sem esta linha, a despesa
        sobreviveria com o campo em branco e seguiria descontando todo mês uma
        parcela de financiamento que não existe mais — sem nenhuma tela onde o
        cliente entendesse de onde ela veio.

        Os lançamentos já materializados nos meses passados ficam: são
        histórico do que foi realmente pago.
        """
        instance.despesas_recorrentes.all().delete()
        instance.delete()


class LifeGoalViewSet(_ScopedViewSet):
    queryset = LifeGoal.objects.select_related("membro").all()
    serializer_class = LifeGoalSerializer
