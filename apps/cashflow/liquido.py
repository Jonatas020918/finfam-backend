"""O que de fato cai na conta.

Salário CLT tem INSS e IRPF retidos na fonte: quem tem carteira assinada de
R$ 24.000 não recebe R$ 24.000. Registrar o bruto como receita infla o fluxo
de caixa, infla a taxa de poupança, e leva a projeção de patrimônio a prometer
um dinheiro que nunca existiu.

O erro é grande justamente no público desta plataforma. Numa renda alta, a
retenção passa de 25% — a diferença entre bruto e líquido não é detalhe, é o
tamanho de uma parcela de financiamento.

PJ e autônomo não passam por aqui. No PJ a empresa fatura o valor cheio e
recolhe os tributos depois, em guia separada — o que entra na conta é o que
foi faturado, e o imposto aparece como despesa própria. Descontar aqui seria
cobrar duas vezes.
"""

from dataclasses import dataclass
from decimal import Decimal

from apps.households.models import RegimeTributario, TipoMembro
from apps.simulators.services import EntradaSimulacao, simular_clt


@dataclass(frozen=True)
class ValorLiquido:
    """O bruto informado, o que sobra, e o que foi retido."""

    bruto: Decimal
    liquido: Decimal
    retido: Decimal

    @property
    def houve_retencao(self) -> bool:
        return self.retido > 0


def dependentes_do_household(household) -> int:
    """Dependentes reduzem a base do IRPF.

    São contados do núcleo familiar inteiro, e não por membro, porque é assim
    que a declaração funciona — os dependentes são de quem declara.
    """
    return household.membros.filter(tipo=TipoMembro.DEPENDENTE).count()


def liquido_da_fonte(fonte, valor_bruto: Decimal | None = None) -> ValorLiquido:
    """Quanto desta fonte de renda chega à conta do titular.

    Aceita `valor_bruto` avulso para o caso da renda variável, em que o valor
    do mês é digitado na hora e não é o cadastrado na fonte.
    """
    bruto = Decimal(valor_bruto if valor_bruto is not None else fonte.valor_medio_mensal)

    if fonte.regime != RegimeTributario.CLT or not fonte.valor_e_bruto or bruto <= 0:
        return ValorLiquido(bruto=bruto, liquido=bruto, retido=Decimal("0"))

    resultado = simular_clt(
        EntradaSimulacao(
            receita_bruta_mensal=bruto,
            dependentes=dependentes_do_household(fonte.household),
        )
    )
    liquido = Decimal(resultado.liquido_mensal)
    return ValorLiquido(bruto=bruto, liquido=liquido, retido=bruto - liquido)
