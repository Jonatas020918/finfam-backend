from datetime import date

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.cashflow.services import base_para_simulacao
from apps.common.api import HouseholdScopedMixin, household_do_usuario
from apps.reports.services import medias_do_periodo, patrimonio_liquido

from .amortizacao import simular_amortizacao
from .models import SimulationRun
from .projecao import Premissas, projetar
from .rules import VERSAO_REGRAS
from .serializers import (
    EntradaAmortizacaoSerializer,
    EntradaProjecaoSerializer,
    EntradaSimulacaoSerializer,
    SimulationRunSerializer,
)
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


class AmortizacaoView(APIView):
    """POST /api/simuladores/amortizacao/ — quitação de financiamento.

    Aceita uma dívida cadastrada (caminho comum) ou os números soltos, para
    avaliar um contrato que a pessoa ainda está considerando.
    """

    @extend_schema(request=EntradaAmortizacaoSerializer, responses={200: dict})
    def post(self, request):
        serializer = EntradaAmortizacaoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dados = serializer.validated_data

        household = household_do_usuario(request.user)
        divida = None
        if dados.get("divida"):
            if household is None:
                raise NotFound("Usuário não possui núcleo familiar vinculado.")
            divida = household.dividas.filter(pk=dados["divida"]).first()
            if divida is None:
                raise NotFound("Dívida não encontrada neste núcleo familiar.")

        if divida is not None:
            resultado = simular_amortizacao(
                saldo_devedor=divida.saldo_devedor,
                taxa_mensal_percentual=divida.taxa_juros_mensal,
                parcelas_restantes=divida.parcelas_a_pagar or divida.parcelas_restantes,
                sistema=divida.sistema,
                aporte_extra_mensal=dados["aporte_extra_mensal"],
                aporte_unico=dados["aporte_unico"],
                estrategia=dados["estrategia"],
                parcelas_pagas=divida.parcelas_pagas,
                parcelas_totais=divida.parcelas_totais,
            )
            resultado["divida"] = {
                "id": str(divida.id),
                "descricao": divida.descricao,
                "tipo": divida.get_tipo_display(),
                "valor_parcela_atual": divida.valor_parcela,
            }
        else:
            resultado = simular_amortizacao(
                saldo_devedor=dados["saldo_devedor"],
                taxa_mensal_percentual=dados["taxa_juros_mensal"],
                parcelas_restantes=dados["parcelas_restantes"],
                sistema=dados["sistema"],
                aporte_extra_mensal=dados["aporte_extra_mensal"],
                aporte_unico=dados["aporte_unico"],
                estrategia=dados["estrategia"],
            )

        return Response(resultado)


class BaseRealParaSimulacaoView(APIView):
    """GET /api/simuladores/base-real/ — renda efetivamente lançada no mês.

    Serve para a tela do simulador partir do que a pessoa recebeu de fato, em
    vez de pedir que ela redigite o valor (e erre). A classificação por regime
    vem dos lançamentos de fluxo de caixa vinculados às fontes de renda.
    """

    @extend_schema(
        parameters=[OpenApiParameter("ano", int), OpenApiParameter("mes", int)],
        responses={200: dict},
    )
    def get(self, request):
        household = household_do_usuario(request.user)
        if household is None:
            raise NotFound("Usuário não possui núcleo familiar vinculado.")

        hoje = date.today()
        ano = int(request.query_params.get("ano", hoje.year))
        mes = int(request.query_params.get("mes", hoje.month))
        return Response(base_para_simulacao(household, ano, mes))


class ProjecaoView(APIView):
    """GET/POST /api/simuladores/projecao/ — patrimônio projetado a longo prazo.

    A base vem do histórico real do núcleo familiar; as premissas vêm do
    cliente. GET usa os padrões, POST permite ajustar tudo.
    """

    @extend_schema(
        parameters=[
            OpenApiParameter("meses_base", int, description="1 a 24 (padrão 12)"),
            OpenApiParameter("anos", int, description="1 a 15 (padrão 10)"),
            OpenApiParameter("rentabilidade_real_anual", float),
        ],
        responses={200: dict},
    )
    def get(self, request):
        return self._projetar(request, request.query_params)

    @extend_schema(request=EntradaProjecaoSerializer, responses={200: dict})
    def post(self, request):
        return self._projetar(request, request.data)

    def _projetar(self, request, dados_brutos):
        serializer = EntradaProjecaoSerializer(data=dados_brutos)
        serializer.is_valid(raise_exception=True)
        dados = serializer.validated_data

        household = household_do_usuario(request.user)
        if household is None:
            raise NotFound("Usuário não possui núcleo familiar vinculado.")

        hoje = date.today()
        medias = medias_do_periodo(household, hoje.year, hoje.month, dados["meses_base"])
        patrimonio = patrimonio_liquido(household)

        premissas = Premissas(
            meses_base=dados["meses_base"],
            anos=dados["anos"],
            rentabilidade_real_anual=dados["rentabilidade_real_anual"],
            crescimento_renda_anual=dados["crescimento_renda_anual"],
            inflacao_despesas_anual=dados["inflacao_despesas_anual"],
            aporte_mensal_manual=dados.get("aporte_mensal_manual"),
        )

        resultado = projetar(
            receitas_medias=medias["receitas_medias"],
            despesas_medias=medias["despesas_medias"],
            patrimonio_inicial=patrimonio["liquido"],
            premissas=premissas,
        )
        resultado["historico_base"] = medias["serie"]
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
