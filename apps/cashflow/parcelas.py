"""A parcela do financiamento como despesa do mês.

Quem cadastra um financiamento no onboarding informa a parcela mensal — e
depois não a encontra em lugar nenhum. O fluxo de caixa mostra as receitas
completas e esconde a maior saída fixa da família, e o saldo do mês fica
otimista pelo tamanho exato da prestação.

A dívida e a despesa são coisas diferentes e as duas precisam existir. A
dívida é o saldo devedor, que serve à simulação de quitação. A despesa é o que
sai da conta todo mês. Ligar uma à outra é o que mantém as duas telas
contando a mesma história.
"""

from datetime import date

from .models import CategoriaLancamento, RecurringExpense


def _somar_meses(inicio: date, meses: int) -> date:
    """Avança N meses preservando o dia 1.

    Aritmética à mão em vez de `relativedelta`: o dateutil está instalado
    apenas como dependência do Celery, e amarrar uma regra de negócio a um
    pacote que entrou de carona quebra no dia em que o Celery trocar de
    dependência.
    """
    total = inicio.year * 12 + (inicio.month - 1) + meses
    return date(total // 12, total % 12 + 1, 1)


def _fim_da_vigencia(divida, inicio: date) -> date | None:
    """Quando a última parcela cai.

    Financiamento tem fim, e a despesa precisa parar sozinha nele — senão o
    cliente vê a parcela de um carro já quitado saindo do orçamento dele por
    anos. Dívida sem número de parcelas (cheque especial, rotativo) não tem
    data para acabar, e aí a vigência fica em aberto mesmo.

    Conta por `parcelas_a_pagar`, e não pelo campo `parcelas_restantes`: o
    formulário pede o prazo contratado e a data da primeira parcela, e é dali
    que sai quanto falta. Ler o campo cru fazia toda dívida cadastrada pela
    tela cair no caso "sem prazo" — a parcela ficava saindo do orçamento para
    sempre, que é exatamente o que este código existe para impedir.
    """
    faltam = divida.parcelas_a_pagar
    if not faltam:
        return None
    return _somar_meses(inicio, faltam - 1)


def sincronizar_despesa(divida) -> RecurringExpense | None:
    """Cria ou atualiza a despesa fixa correspondente à parcela.

    Idempotente: chamar de novo com os mesmos dados não duplica nada. É a
    dívida que manda — editar a parcela lá reflete aqui, porque as duas telas
    descrevem o mesmo compromisso.
    """
    if not divida.valor_parcela or divida.valor_parcela <= 0:
        # Sem parcela informada não há o que lançar. Se havia uma despesa de
        # antes, ela some junto: manter uma parcela de valor zero no orçamento
        # é ruído.
        RecurringExpense.objects.filter(divida=divida).delete()
        return None

    inicio = divida.data_primeira_parcela or date.today().replace(day=1)

    despesa, _ = RecurringExpense.objects.update_or_create(
        divida=divida,
        defaults={
            "household": divida.household,
            "tenant": divida.tenant,
            "membro": divida.membro,
            "descricao": divida.descricao,
            "categoria": CategoriaLancamento.DIVIDA,
            "valor_previsto": divida.valor_parcela,
            "vigencia_inicio": inicio,
            "vigencia_fim": _fim_da_vigencia(divida, inicio),
            "ativa": True,
        },
    )
    return despesa
