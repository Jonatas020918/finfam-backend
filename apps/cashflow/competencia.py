"""Abertura de competência: transforma o que é fixo em lançamentos do mês.

O produto tem dois jeitos de registrar dinheiro, e a diferença é do usuário, não
do sistema:

  fixo     — cadastrado uma vez (salário, aluguel, escola, parcela) e repetido
             todo mês pela plataforma;
  variável — lançado mês a mês porque o valor muda (plantão, consultório,
             mercado).

Os dois terminam como `CashFlowEntry`. Essa é a regra que sustenta o resto: o
fluxo de caixa, o dashboard, o simulador e a projeção leem **apenas
lançamentos**, nunca "valor médio cadastrado". Antes disso existiam duas
verdades paralelas, e elas discordavam.

Abrir a competência é idempotente e **nunca sobrescreve valor já existente**:
o cadastro semeia o mês, e qualquer ajuste que o usuário faça naquele mês vence.
"""

from dataclasses import dataclass
from datetime import date

from django.db import transaction

from apps.households.models import IncomeSource

from .models import CashFlowEntry, RecurringExpense, TipoLancamento

CATEGORIA_POR_TIPO_RENDA = {
    "aluguel": "renda_investimento",
}


@dataclass
class ResultadoAbertura:
    ano: int
    mes: int
    receitas_criadas: int
    despesas_criadas: int
    ja_existiam: int

    @property
    def criados(self) -> int:
        return self.receitas_criadas + self.despesas_criadas


@transaction.atomic
def abrir_competencia(household, ano: int, mes: int) -> ResultadoAbertura:
    """Garante que todo item fixo tenha lançamento nesta competência."""
    receitas = _materializar_receitas_fixas(household, ano, mes)
    despesas = _materializar_despesas_recorrentes(household, ano, mes)

    return ResultadoAbertura(
        ano=ano,
        mes=mes,
        receitas_criadas=receitas[0],
        despesas_criadas=despesas[0],
        ja_existiam=receitas[1] + despesas[1],
    )


def _materializar_receitas_fixas(household, ano: int, mes: int) -> tuple[int, int]:
    criados = existentes = 0

    fontes = IncomeSource.objects.filter(
        household=household, ativa=True, modo_lancamento="fixa"
    ).select_related("membro")

    for fonte in fontes:
        _, criado = CashFlowEntry.objects.get_or_create(
            household=household,
            fonte_renda=fonte,
            ano=ano,
            mes=mes,
            defaults={
                "tenant": household.tenant,
                "membro": fonte.membro,
                "tipo": TipoLancamento.RECEITA,
                "categoria": CATEGORIA_POR_TIPO_RENDA.get(fonte.tipo, "renda_trabalho"),
                "descricao": fonte.descricao,
                "valor_realizado": fonte.valor_medio_mensal,
                "valor_orcado": fonte.valor_medio_mensal,
                "regime": fonte.regime,
                "tipo_renda": fonte.tipo,
            },
        )
        criados += int(criado)
        existentes += int(not criado)

    return criados, existentes


def _materializar_despesas_recorrentes(household, ano: int, mes: int) -> tuple[int, int]:
    criados = existentes = 0

    recorrentes = RecurringExpense.objects.filter(
        household=household, ativa=True
    ).select_related("membro")

    for recorrente in recorrentes:
        if not recorrente.vigente_em(ano, mes):
            continue

        _, criado = CashFlowEntry.objects.get_or_create(
            household=household,
            despesa_recorrente=recorrente,
            ano=ano,
            mes=mes,
            defaults={
                "tenant": household.tenant,
                "membro": recorrente.membro,
                "tipo": TipoLancamento.DESPESA,
                "categoria": recorrente.categoria,
                "descricao": recorrente.descricao,
                "valor_realizado": recorrente.valor_previsto,
                "valor_orcado": recorrente.valor_previsto,
            },
        )
        criados += int(criado)
        existentes += int(not criado)

    return criados, existentes


def competencias_com_movimento(household, limite: int = 24) -> list[dict]:
    """Meses que já têm lançamento, do mais recente para o mais antigo.

    Alimenta o seletor de mês: em vez de o usuário caçar às cegas em qual mês
    lançou alguma coisa, a interface mostra onde há dado.
    """
    hoje = date.today()
    linhas = (
        CashFlowEntry.objects.filter(household=household)
        .values("ano", "mes")
        .distinct()
        .order_by("-ano", "-mes")[:limite]
    )
    competencias = [{"ano": linha["ano"], "mes": linha["mes"]} for linha in linhas]

    # O mês corrente sempre aparece, mesmo vazio: é onde o usuário vai lançar.
    atual = {"ano": hoje.year, "mes": hoje.month}
    if atual not in competencias:
        competencias.insert(0, atual)

    return competencias
