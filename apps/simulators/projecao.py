"""Projeção financeira de longo prazo.

Parte do que a família realmente movimentou (não de um valor estimado) e
projeta o patrimônio ano a ano. A janela de histórico é escolhida pelo cliente:
1 a 24 meses. Janelas curtas reagem rápido a mudanças de vida; janelas longas
suavizam a sazonalidade de plantão — por isso a escolha é dele, não nossa.

Premissas ficam explícitas na resposta. Uma projeção sem premissas visíveis é
uma adivinhação com aparência de certeza — e este módulo é educacional, nunca
promessa de retorno.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

D = Decimal
ZERO = D("0.00")

MAX_MESES_BASE = 24
MAX_ANOS_PROJECAO = 15


def _brl(valor: Decimal) -> Decimal:
    return Decimal(valor).quantize(D("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Premissas:
    meses_base: int
    anos: int
    rentabilidade_real_anual: Decimal
    crescimento_renda_anual: Decimal
    inflacao_despesas_anual: Decimal
    aporte_mensal_manual: Decimal | None = None

    def __post_init__(self):
        if not 1 <= self.meses_base <= MAX_MESES_BASE:
            raise ValueError(f"meses_base deve estar entre 1 e {MAX_MESES_BASE}")
        if not 1 <= self.anos <= MAX_ANOS_PROJECAO:
            raise ValueError(f"anos deve estar entre 1 e {MAX_ANOS_PROJECAO}")


def _taxa_mensal_equivalente(taxa_anual: Decimal) -> Decimal:
    """Converte taxa anual em mensal equivalente: (1+i)^(1/12) − 1."""
    if taxa_anual == 0:
        return ZERO
    return Decimal((1 + float(taxa_anual) / 100) ** (1 / 12) - 1)


def projetar(
    receitas_medias: Decimal,
    despesas_medias: Decimal,
    patrimonio_inicial: Decimal,
    premissas: Premissas,
    referencia: date | None = None,
) -> dict:
    """Projeta patrimônio ano a ano a partir da média observada.

    O aporte mensal é o que sobra (receitas − despesas), corrigido a cada ano
    pelas taxas de crescimento informadas. O patrimônio rende à taxa real
    informada — real, isto é, já descontada a inflação, para que os valores
    projetados sejam comparáveis ao poder de compra de hoje.
    """
    referencia = referencia or date.today()

    receitas = Decimal(receitas_medias)
    despesas = Decimal(despesas_medias)
    sobra_mensal = (
        Decimal(premissas.aporte_mensal_manual)
        if premissas.aporte_mensal_manual is not None
        else receitas - despesas
    )

    taxa_mensal = _taxa_mensal_equivalente(premissas.rentabilidade_real_anual)
    patrimonio = Decimal(patrimonio_inicial)
    total_aportado = ZERO
    total_rendimento = ZERO

    serie = [
        {
            "ano": referencia.year,
            "mes_referencia": referencia.month,
            "ordem": 0,
            "patrimonio": _brl(patrimonio),
            "aportado_no_ano": ZERO,
            "rendimento_no_ano": ZERO,
            "aporte_mensal": _brl(sobra_mensal),
        }
    ]

    aporte_corrente = sobra_mensal
    receitas_correntes = receitas
    despesas_correntes = despesas

    for ano in range(1, premissas.anos + 1):
        aportado_ano = ZERO
        rendimento_ano = ZERO

        for _ in range(12):
            rendimento = patrimonio * taxa_mensal
            patrimonio += rendimento + aporte_corrente
            rendimento_ano += rendimento
            aportado_ano += aporte_corrente

        total_aportado += aportado_ano
        total_rendimento += rendimento_ano

        serie.append(
            {
                "ano": referencia.year + ano,
                "mes_referencia": referencia.month,
                "ordem": ano,
                "patrimonio": _brl(patrimonio),
                "aportado_no_ano": _brl(aportado_ano),
                "rendimento_no_ano": _brl(rendimento_ano),
                "aporte_mensal": _brl(aporte_corrente),
            }
        )

        # Correção anual: renda e despesa crescem em ritmos que podem diferir —
        # é justamente esse descompasso que aperta ou folga o orçamento.
        receitas_correntes *= 1 + premissas.crescimento_renda_anual / 100
        despesas_correntes *= 1 + premissas.inflacao_despesas_anual / 100
        if premissas.aporte_mensal_manual is None:
            aporte_corrente = receitas_correntes - despesas_correntes
        else:
            aporte_corrente = Decimal(premissas.aporte_mensal_manual)

    return {
        "base": {
            "meses_considerados": premissas.meses_base,
            "receitas_medias_mensais": _brl(receitas),
            "despesas_medias_mensais": _brl(despesas),
            "sobra_media_mensal": _brl(sobra_mensal),
            "patrimonio_inicial": _brl(Decimal(patrimonio_inicial)),
            "taxa_poupanca_percentual": (
                (sobra_mensal / receitas * 100).quantize(D("0.01")) if receitas else ZERO
            ),
        },
        "premissas": {
            "anos_projetados": premissas.anos,
            "rentabilidade_real_anual": premissas.rentabilidade_real_anual,
            "crescimento_renda_anual": premissas.crescimento_renda_anual,
            "inflacao_despesas_anual": premissas.inflacao_despesas_anual,
            "aporte_mensal_manual": (
                _brl(Decimal(premissas.aporte_mensal_manual))
                if premissas.aporte_mensal_manual is not None
                else None
            ),
        },
        "serie": serie,
        "resultado": {
            "patrimonio_final": _brl(patrimonio),
            "total_aportado": _brl(total_aportado),
            "total_rendimento": _brl(total_rendimento),
            "multiplicador": (
                (patrimonio / Decimal(patrimonio_inicial)).quantize(D("0.01"))
                if Decimal(patrimonio_inicial) > 0
                else None
            ),
        },
        "alertas": _alertas(sobra_mensal, premissas),
        "disclaimer": (
            "Projeção educacional construída a partir da sua própria média histórica e "
            "das premissas exibidas acima. Não é previsão nem promessa de retorno: "
            "rentabilidade passada não garante rentabilidade futura, e qualquer mudança "
            "de renda, despesa ou mercado altera o resultado. Valores em poder de compra "
            "de hoje, já que a rentabilidade informada é real (acima da inflação)."
        ),
    }


def _alertas(sobra_mensal: Decimal, premissas: Premissas) -> list[str]:
    alertas = []
    if sobra_mensal <= 0:
        alertas.append(
            "No período analisado suas despesas alcançaram ou superaram suas receitas — "
            "sem sobra mensal, o patrimônio projetado só cresce pela rentabilidade do que "
            "já existe."
        )
    if premissas.meses_base <= 3:
        alertas.append(
            "Base de poucos meses: um plantão atípico ou uma despesa pontual distorce a "
            "média. Para renda variável, 6 a 12 meses costumam representar melhor a realidade."
        )
    if premissas.rentabilidade_real_anual > 8:
        alertas.append(
            "Rentabilidade real acima de 8% ao ano é bastante otimista para um horizonte "
            "longo. Vale rodar também um cenário mais conservador."
        )
    if premissas.anos >= 10:
        alertas.append(
            "Em horizontes de 10 anos ou mais, pequenas diferenças nas premissas mudam "
            "muito o resultado final. Use a projeção como direção, não como número exato."
        )
    return alertas
