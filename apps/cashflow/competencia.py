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
from decimal import Decimal

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


def _competencia_atual(referencia: date | None = None) -> int:
    """Competência como número comparável (ano × 12 + mês)."""
    hoje = referencia or date.today()
    return hoje.year * 12 + hoje.month


def propagar_alteracao(
    lancamentos,
    *,
    valor_anterior: Decimal,
    valor_novo: Decimal,
    descricao_nova: str | None = None,
    extras: dict | None = None,
    referencia: date | None = None,
) -> int:
    """Reflete a mudança de um cadastro fixo nos meses ainda em aberto.

    Duas fronteiras deliberadas:

    **Só do mês corrente em diante.** Meses passados são histórico: se o aluguel
    subiu agora, o que foi pago em março continua sendo o que foi pago em março.
    Reescrever o passado destruiria o comparativo orçado x realizado.

    **Só o que não foi ajustado à mão.** Se o lançamento do mês ainda tem
    exatamente o valor antigo do cadastro, ninguém mexeu nele — pode acompanhar.
    Se está diferente, o usuário já corrigiu para aquele mês, e a correção dele
    vale mais que o cadastro.

    A descrição, essa sim, acompanha sempre: renomear "Aluguel" para "Aluguel
    apto novo" é o mesmo item, e deixar os dois nomes convivendo confunde.
    """
    limite = _competencia_atual(referencia)
    atualizados = 0

    for lancamento in lancamentos:
        if lancamento.ano * 12 + lancamento.mes < limite:
            continue

        campos = []
        if descricao_nova and lancamento.descricao != descricao_nova:
            lancamento.descricao = descricao_nova
            campos.append("descricao")

        if Decimal(lancamento.valor_realizado) == Decimal(valor_anterior):
            lancamento.valor_realizado = valor_novo
            lancamento.valor_orcado = valor_novo
            campos += ["valor_realizado", "valor_orcado"]

        for campo, valor in (extras or {}).items():
            if getattr(lancamento, campo) != valor:
                setattr(lancamento, campo, valor)
                campos.append(campo)

        if campos:
            lancamento.save(update_fields=[*set(campos), "atualizado_em"])
            atualizados += 1

    return atualizados


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
