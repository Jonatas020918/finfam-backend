"""Lançamento mensal de renda por fonte.

Quem não vive só de salário tem renda que oscila muito entre os meses — o
serviço avulso varia, o negócio próprio tem sazonalidade. Registrar o valor
real de cada fonte a cada mês é o que dá base confiável para o simulador
tributário e para a projeção.

A operação é **idempotente por (fonte, ano, mês)**: lançar de novo a mesma
competência corrige o valor em vez de duplicar a receita. Sem isso, quem
registrasse o mesmo mês duas vezes veria a renda dobrada no dashboard.
"""

from decimal import Decimal

from django.db import transaction

from .liquido import liquido_da_fonte
from .models import CashFlowEntry, CategoriaLancamento, TipoLancamento

CATEGORIA_POR_TIPO_RENDA = {
    "aluguel": CategoriaLancamento.RENDA_INVESTIMENTO,
}


@transaction.atomic
def registrar_competencia(fonte, ano: int, mes: int, valor: Decimal, valor_orcado=None):
    """Cria ou atualiza o lançamento daquela fonte naquela competência.

    O valor recebido é o que a pessoa digitou. Num plantão CLT, ela digita o
    bruto do contracheque — e quem lança R$ 12.000 de plantão não viu R$ 12.000
    na conta. A retenção é aplicada aqui, com a mesma regra da renda fixa.
    """
    categoria = CATEGORIA_POR_TIPO_RENDA.get(fonte.tipo, CategoriaLancamento.RENDA_TRABALHO)
    recebido = liquido_da_fonte(fonte, Decimal(valor))
    orcado = liquido_da_fonte(
        fonte, Decimal(valor_orcado) if valor_orcado is not None else None
    )

    lancamento, criado = CashFlowEntry.objects.update_or_create(
        household=fonte.household,
        fonte_renda=fonte,
        ano=ano,
        mes=mes,
        defaults={
            "tenant": fonte.tenant,
            "membro": fonte.membro,
            "tipo": TipoLancamento.RECEITA,
            "categoria": categoria,
            "descricao": fonte.descricao,
            "valor_realizado": recebido.liquido,
            "valor_orcado": orcado.liquido,
            "valor_bruto": recebido.bruto if recebido.houve_retencao else None,
            "regime": fonte.regime,
            "tipo_renda": fonte.tipo,
        },
    )
    return lancamento, criado


def historico_da_fonte(fonte, meses: int = 12) -> list[dict]:
    """Últimas competências lançadas, da mais recente para a mais antiga."""
    return [
        {
            "ano": lancamento.ano,
            "mes": lancamento.mes,
            "valor_realizado": lancamento.valor_realizado,
            "valor_orcado": lancamento.valor_orcado,
        }
        for lancamento in fonte.lancamentos.order_by("-ano", "-mes")[:meses]
    ]
