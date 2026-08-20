"""Direitos do titular sobre os próprios dados.

A LGPD dá ao titular, entre outros, o direito de **acessar** os dados que a
plataforma guarda sobre ele (art. 18, II) e o de pedir a **eliminação** deles
(art. 18, VI). Este módulo implementa os dois.

Uma decisão atravessa o arquivo inteiro e vale explicar: eliminar não é apagar
tudo. O art. 16, I ressalva o que o controlador precisa manter por obrigação
legal — e um serviço que emitiu nota fiscal precisa manter o registro daquela
cobrança pelo prazo fiscal, mesmo depois de o cliente sair.

A saída honesta é apagar tudo que é pessoal e financeiro do titular, e manter
apenas o rastro mínimo de cobrança, **anonimizado**: sem nome, sem e-mail, sem
documento. O que resta não identifica ninguém e não serve para outra coisa.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.billing.models import DadosFiscais, Subscription
from apps.cashflow.models import CashFlowEntry, RecurringExpense
from apps.goals.models import Goal
from apps.households.models import Asset, Debt, Household, IncomeSource, LifeGoal, Member
from apps.reports.models import ClientReport
from apps.simulators.models import SimulationRun


def _serializavel(valor):
    """Converte o que o JSON não sabe representar."""
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, datetime | date):
        return valor.isoformat()
    return valor


def _registros(modelo, household, campos):
    return [
        {campo: _serializavel(getattr(item, campo)) for campo in campos}
        for item in modelo.objects.filter(household=household)
    ]


def exportar(household: Household, usuario) -> dict:
    """Tudo que a plataforma guarda deste núcleo familiar.

    O formato é JSON legível, não um despejo do banco: quem exerce o direito de
    acesso precisa **entender** o que recebe. Nomes de campo em português, datas
    por extenso no cabeçalho, e nenhum identificador interno que não signifique
    nada para o titular.
    """
    return {
        "gerado_em": timezone.now().isoformat(),
        "aviso": (
            "Esta é a cópia integral dos dados que o Batimento guarda sobre o seu "
            "núcleo familiar, conforme o art. 18 da LGPD. Guarde o arquivo em local "
            "seguro: ele contém informações financeiras detalhadas."
        ),
        "titular": {
            "nome_completo": usuario.nome_completo,
            "email": usuario.email,
            "telefone": usuario.telefone,
            "conta_criada_em": _serializavel(usuario.criado_em),
            "ultimo_acesso": _serializavel(usuario.last_login),
        },
        "nucleo_familiar": {
            "nome": household.nome,
            "estado_civil": household.estado_civil,
            "regime_bens": household.regime_bens,
            "criado_em": _serializavel(household.criado_em),
        },
        "membros": _registros(
            Member, household, ["nome", "tipo", "data_nascimento", "profissao"]
        ),
        "fontes_de_renda": _registros(
            IncomeSource,
            household,
            ["descricao", "tipo", "regime", "valor_medio_mensal", "variabilidade_percentual"],
        ),
        "patrimonio": _registros(
            Asset, household, ["descricao", "tipo", "valor_atual", "titularidade"]
        ),
        "dividas": _registros(
            Debt,
            household,
            ["descricao", "tipo", "saldo_devedor", "taxa_juros_mensal", "valor_parcela"],
        ),
        "objetivos": _registros(LifeGoal, household, ["descricao", "categoria", "horizonte_anos"]),
        "metas": _registros(
            Goal, household, ["descricao", "valor_alvo", "valor_atual", "prazo"]
        ),
        "despesas_fixas": _registros(
            RecurringExpense,
            household,
            ["descricao", "categoria", "valor_previsto", "vigencia_inicio", "vigencia_fim"],
        ),
        "lancamentos": _registros(
            CashFlowEntry,
            household,
            ["ano", "mes", "tipo", "categoria", "descricao", "valor_previsto", "valor_realizado"],
        ),
        "simulacoes": _registros(SimulationRun, household, ["tipo", "criado_em"]),
        "assinatura": _registros(
            Subscription,
            household,
            ["status", "inicio", "trial_termina_em", "proxima_cobranca", "cancelada_em"],
        ),
        "dados_de_faturamento": _registros(
            DadosFiscais,
            household,
            ["razao_social", "documento", "cep", "logradouro", "numero", "cidade", "uf"],
        ),
    }


@dataclass
class ResultadoDaExclusao:
    """O que foi apagado, para o titular poder conferir."""

    registros_apagados: int
    assinaturas_anonimizadas: int


# Modelos cujos registros são do titular e somem por inteiro. Subscription
# fica de fora de propósito: é o rastro de cobrança que a lei manda guardar.
_MODELOS_DO_TITULAR = (
    CashFlowEntry,
    RecurringExpense,
    SimulationRun,
    Goal,
    ClientReport,
    LifeGoal,
    Debt,
    Asset,
    IncomeSource,
    DadosFiscais,
    Member,
)


@transaction.atomic
def excluir_conta(usuario) -> ResultadoDaExclusao:
    """Elimina os dados do titular, preservando o mínimo legal.

    Tudo em uma transação: uma exclusão que falha no meio deixaria a conta num
    estado pior que qualquer um dos dois extremos — dados financeiros
    parcialmente apagados e nenhuma forma de saber o que sobrou.
    """
    from apps.common.api import household_do_usuario

    household = household_do_usuario(usuario)
    apagados = 0

    if household is not None:
        for modelo in _MODELOS_DO_TITULAR:
            quantidade, _ = modelo.objects.filter(household=household).delete()
            apagados += quantidade

    # O registro de cobrança permanece, sem identificar ninguém: os dados
    # fiscais já foram apagados acima, e aqui some o vínculo com o gateway.
    anonimizadas = 0
    if household is not None:
        anonimizadas = Subscription.objects.filter(household=household).update(
            gateway_customer_id="",
            gateway_subscription_id="",
        )

    if household is not None:
        household.nome = "Núcleo excluído a pedido do titular"
        household.save(update_fields=["nome", "atualizado_em"])

    # O usuário some por último, e some de verdade: e-mail e nome são o que
    # identifica a pessoa, e nenhuma obrigação legal exige mantê-los.
    usuario.delete()
    apagados += 1

    return ResultadoDaExclusao(
        registros_apagados=apagados, assinaturas_anonimizadas=anonimizadas
    )
