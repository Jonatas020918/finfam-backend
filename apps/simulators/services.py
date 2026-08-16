"""Motor de cálculo do simulador PJ x CLT x Autônomo (seção 3.3).

Regras de projeto:
  - Puro Python: nenhuma dependência de banco, request ou usuário. Isso torna o
    motor testável isoladamente e reutilizável no relatório em PDF.
  - Toda saída acompanha `explicacao` em linguagem simples — requisito do modo
    self-service, onde não há consultor para interpretar o número.
  - É uma simulação simplificada para planejamento. Não substitui orientação
    contábil formal (disclaimer obrigatório, seção 8).
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from . import rules
from .rules import D

DISCLAIMER_SIMULADOR = (
    "Simulação simplificada para fins de planejamento financeiro. Não considera "
    "todas as particularidades da sua situação (benefícios, deduções específicas, "
    "ISS municipal, entre outras) e não substitui a orientação de um contador."
)


ZERO = D("0")


def _brl(valor: Decimal) -> Decimal:
    return Decimal(valor).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def _pct(valor: Decimal) -> Decimal:
    return Decimal(valor).quantize(D("0.0001"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class EntradaSimulacao:
    """Dados informados pelo usuário. Um único conjunto alimenta os 3 regimes."""

    receita_bruta_mensal: Decimal
    dependentes: int = 0

    # CLT
    beneficios_nao_tributaveis_mensais: Decimal = ZERO

    # PJ
    pro_labore_mensal: Decimal | None = None  # None ⇒ usa o mínimo do Fator R
    despesas_pj_mensais: Decimal = ZERO     # contador, conta PJ, certificado
    anexo_simples: str = "auto"               # "auto" | "III" | "V"

    # Autônomo
    despesas_livro_caixa_mensais: Decimal = ZERO
    inss_autonomo_retido_na_fonte: bool = False

    def __post_init__(self):
        if self.receita_bruta_mensal is None or Decimal(self.receita_bruta_mensal) <= 0:
            raise ValueError("receita_bruta_mensal deve ser maior que zero")
        if self.dependentes < 0:
            raise ValueError("dependentes não pode ser negativo")


@dataclass
class ResultadoRegime:
    regime: str
    rotulo: str
    receita_bruta_mensal: Decimal
    inss_mensal: Decimal
    irpf_mensal: Decimal
    outros_tributos_mensais: Decimal
    custos_mensais: Decimal
    liquido_mensal: Decimal
    liquido_anual: Decimal
    carga_tributaria_efetiva: Decimal
    detalhes: dict = field(default_factory=dict)
    explicacao: list[str] = field(default_factory=list)
    alertas: list[str] = field(default_factory=list)


# --- IRPF ------------------------------------------------------------------

def calcular_irpf_mensal(
    base_tributavel: Decimal,
    dependentes: int = 0,
    deducoes_adicionais: Decimal = ZERO,
    usar_desconto_simplificado: bool = True,
) -> tuple[Decimal, dict]:
    """IRPF mensal pela tabela progressiva.

    Compara a dedução legal (dependentes + deduções informadas) com o desconto
    simplificado e usa a mais vantajosa, como faz a própria Receita.
    """
    base_tributavel = Decimal(base_tributavel)
    deducao_legal = (
        rules.IRPF_DEDUCAO_DEPENDENTE * dependentes + Decimal(deducoes_adicionais)
    )
    deducao = deducao_legal
    modo = "deducoes_legais"
    if usar_desconto_simplificado and rules.IRPF_DESCONTO_SIMPLIFICADO > deducao_legal:
        deducao = rules.IRPF_DESCONTO_SIMPLIFICADO
        modo = "desconto_simplificado"

    base = max(base_tributavel - deducao, D("0"))
    for teto, aliquota, parcela in rules.IRPF_FAIXAS:
        if base <= teto:
            imposto = max(base * aliquota - parcela, D("0"))
            return _brl(imposto), {
                "base_calculo": _brl(base),
                "aliquota_faixa": _pct(aliquota),
                "parcela_deduzir": _brl(parcela),
                "deducao_aplicada": _brl(deducao),
                "modo_deducao": modo,
            }
    return D("0"), {}


def calcular_inss_clt(salario: Decimal) -> Decimal:
    base = min(Decimal(salario), rules.INSS_TETO_SALARIO_CONTRIBUICAO)
    return _brl(rules.faixa_progressiva(base, rules.INSS_FAIXAS_CLT))


# --- Regimes ---------------------------------------------------------------

def simular_clt(e: EntradaSimulacao) -> ResultadoRegime:
    bruto = Decimal(e.receita_bruta_mensal)
    inss = calcular_inss_clt(bruto)
    base_ir = bruto - inss
    irpf, det_ir = calcular_irpf_mensal(
        base_ir, dependentes=e.dependentes, deducoes_adicionais=D("0")
    )
    liquido = bruto - inss - irpf + Decimal(e.beneficios_nao_tributaveis_mensais)

    # No CLT o ano tem 13,33 salários (13º + 1/3 de férias) e o FGTS é depósito
    # do empregador — não entra no líquido do mês, mas é patrimônio do trabalhador.
    liquido_anual = liquido * rules.CLT_SALARIOS_POR_ANO
    fgts_anual = bruto * rules.FGTS_PERCENTUAL * rules.CLT_SALARIOS_POR_ANO

    carga = (inss + irpf) / bruto if bruto else D("0")
    return ResultadoRegime(
        regime="clt",
        rotulo="CLT",
        receita_bruta_mensal=_brl(bruto),
        inss_mensal=inss,
        irpf_mensal=irpf,
        outros_tributos_mensais=D("0.00"),
        custos_mensais=D("0.00"),
        liquido_mensal=_brl(liquido),
        liquido_anual=_brl(liquido_anual),
        carga_tributaria_efetiva=_pct(carga),
        detalhes={
            "irpf": det_ir,
            "fgts_anual_estimado": _brl(fgts_anual),
            "salarios_por_ano": str(rules.CLT_SALARIOS_POR_ANO),
            "beneficios_nao_tributaveis": _brl(Decimal(e.beneficios_nao_tributaveis_mensais)),
        },
        explicacao=[
            f"No CLT o INSS é descontado direto na folha (R$ {inss}) e o imposto de "
            f"renda incide sobre o que sobra (R$ {irpf}).",
            "O ano tem 13,33 salários por causa do 13º e do terço de férias — por "
            "isso o valor anual é maior que 12 vezes o líquido do mês.",
            f"Além do líquido, o empregador deposita FGTS: cerca de R$ {_brl(fgts_anual)} por ano.",
        ],
    )


def simular_pj(e: EntradaSimulacao) -> ResultadoRegime:
    bruto = Decimal(e.receita_bruta_mensal)
    rbt12 = bruto * 12
    alertas: list[str] = []

    # Pró-labore: se não informado, usa o mínimo que mantém o Fator R em 28%
    # (caminho usual do médico PJ para permanecer no Anexo III).
    pro_labore = (
        Decimal(e.pro_labore_mensal)
        if e.pro_labore_mensal is not None
        else bruto * rules.FATOR_R_LIMITE
    )
    pro_labore = min(pro_labore, bruto)

    fator_r = (pro_labore * 12) / rbt12 if rbt12 else D("0")
    if e.anexo_simples == "III":
        anexo, nome_anexo = rules.SIMPLES_ANEXO_III, "III"
    elif e.anexo_simples == "V":
        anexo, nome_anexo = rules.SIMPLES_ANEXO_V, "V"
    else:
        usa_iii = fator_r >= rules.FATOR_R_LIMITE
        anexo = rules.SIMPLES_ANEXO_III if usa_iii else rules.SIMPLES_ANEXO_V
        nome_anexo = "III" if usa_iii else "V"

    if rbt12 > rules.SIMPLES_ANEXO_III[-1][0]:
        alertas.append(
            "A receita anual projetada ultrapassa o limite do Simples Nacional "
            "(R$ 4,8 milhões). Nesse patamar o cálculo real seria por Lucro "
            "Presumido ou Real — procure seu contador."
        )

    aliquota_efetiva = rules.aliquota_efetiva_simples(rbt12, anexo)
    das = bruto * aliquota_efetiva

    # INSS do sócio sobre o pró-labore (11%), limitado ao teto.
    base_inss = min(pro_labore, rules.INSS_TETO_SALARIO_CONTRIBUICAO)
    inss = _brl(base_inss * rules.INSS_ALIQUOTA_PRO_LABORE)

    # IRPF incide apenas sobre o pró-labore; lucros distribuídos hoje são isentos.
    base_ir = pro_labore - inss
    irpf, det_ir = calcular_irpf_mensal(base_ir, dependentes=e.dependentes)

    lucro_distribuido = max(bruto - das - pro_labore - Decimal(e.despesas_pj_mensais), D("0"))
    ir_dividendos = lucro_distribuido * rules.IR_DIVIDENDOS_PERCENTUAL

    tributos = das + ir_dividendos
    custos = Decimal(e.despesas_pj_mensais)
    liquido = bruto - das - inss - irpf - custos - ir_dividendos
    carga = (das + inss + irpf + ir_dividendos) / bruto if bruto else D("0")

    if pro_labore <= 0:
        alertas.append(
            "Sem pró-labore não há contribuição ao INSS — o que significa ficar "
            "sem cobertura previdenciária (auxílio-doença, aposentadoria)."
        )

    return ResultadoRegime(
        regime="pj",
        rotulo="PJ (Simples Nacional)",
        receita_bruta_mensal=_brl(bruto),
        inss_mensal=inss,
        irpf_mensal=irpf,
        outros_tributos_mensais=_brl(tributos),
        custos_mensais=_brl(custos),
        liquido_mensal=_brl(liquido),
        liquido_anual=_brl(liquido * 12),
        carga_tributaria_efetiva=_pct(carga),
        detalhes={
            "anexo": nome_anexo,
            "fator_r": _pct(fator_r),
            "aliquota_efetiva_simples": _pct(aliquota_efetiva),
            "das_mensal": _brl(das),
            "pro_labore_mensal": _brl(pro_labore),
            "lucro_distribuido_mensal": _brl(lucro_distribuido),
            "ir_sobre_dividendos": _brl(ir_dividendos),
            "rbt12": _brl(rbt12),
            "irpf": det_ir,
        },
        explicacao=[
            f"A empresa recolhe o DAS do Simples pelo Anexo {nome_anexo}, com alíquota "
            f"efetiva de {_pct(aliquota_efetiva * 100)}% sobre o faturamento: R$ {_brl(das)} por mês.",
            f"O Fator R desta simulação é {_pct(fator_r * 100)}%. Acima de 28% os serviços "
            "médicos ficam no Anexo III, que costuma ser bem mais barato que o Anexo V.",
            f"Sobre o pró-labore de R$ {_brl(pro_labore)} incidem INSS (R$ {inss}) e IRPF (R$ {irpf}); "
            "o restante sai como distribuição de lucros, hoje isenta na pessoa física.",
            "No PJ não há 13º, férias nem FGTS: essas reservas precisam sair do seu "
            "próprio fluxo de caixa.",
        ],
        alertas=alertas,
    )


def simular_autonomo(e: EntradaSimulacao) -> ResultadoRegime:
    bruto = Decimal(e.receita_bruta_mensal)
    despesas = Decimal(e.despesas_livro_caixa_mensais)

    aliquota_inss = (
        rules.INSS_ALIQUOTA_PRO_LABORE
        if e.inss_autonomo_retido_na_fonte
        else rules.INSS_ALIQUOTA_CONTRIBUINTE_INDIVIDUAL
    )
    base_inss = min(bruto, rules.INSS_TETO_SALARIO_CONTRIBUICAO)
    inss = _brl(base_inss * aliquota_inss)

    # Carnê-leão: despesas do livro-caixa são dedutíveis da base do IR.
    base_ir = max(bruto - inss - despesas, D("0"))
    irpf, det_ir = calcular_irpf_mensal(
        base_ir, dependentes=e.dependentes, usar_desconto_simplificado=False
    )

    liquido = bruto - inss - irpf - despesas
    carga = (inss + irpf) / bruto if bruto else D("0")

    return ResultadoRegime(
        regime="autonomo",
        rotulo="Autônomo (pessoa física)",
        receita_bruta_mensal=_brl(bruto),
        inss_mensal=inss,
        irpf_mensal=irpf,
        outros_tributos_mensais=D("0.00"),
        custos_mensais=_brl(despesas),
        liquido_mensal=_brl(liquido),
        liquido_anual=_brl(liquido * 12),
        carga_tributaria_efetiva=_pct(carga),
        detalhes={
            "aliquota_inss": _pct(aliquota_inss),
            "despesas_livro_caixa": _brl(despesas),
            "irpf": det_ir,
        },
        explicacao=[
            f"Como pessoa física, o INSS é de {_pct(aliquota_inss * 100)}% sobre a "
            f"remuneração até o teto: R$ {inss} por mês.",
            f"O IRPF vai direto para a faixa mais alta da tabela (R$ {irpf}), porque "
            "a receita inteira é tributável — só o livro-caixa reduz a base.",
            "É o regime mais simples de operar e costuma ser o mais caro em "
            "rendimentos altos.",
        ],
    )


def comparar_regimes(e: EntradaSimulacao) -> dict:
    """Roda os três regimes com a mesma entrada e devolve a comparação pronta."""
    resultados = [simular_clt(e), simular_pj(e), simular_autonomo(e)]
    melhor = max(resultados, key=lambda r: r.liquido_mensal)
    pior = min(resultados, key=lambda r: r.liquido_mensal)
    diferenca_anual = _brl((melhor.liquido_mensal - pior.liquido_mensal) * 12)

    return {
        "versao_regras": rules.VERSAO_REGRAS,
        "ano_referencia": rules.ANO_REFERENCIA,
        "entrada": {
            "receita_bruta_mensal": _brl(Decimal(e.receita_bruta_mensal)),
            "dependentes": e.dependentes,
            "pro_labore_mensal": (
                _brl(Decimal(e.pro_labore_mensal)) if e.pro_labore_mensal is not None else None
            ),
            "despesas_pj_mensais": _brl(Decimal(e.despesas_pj_mensais)),
            "despesas_livro_caixa_mensais": _brl(Decimal(e.despesas_livro_caixa_mensais)),
            "anexo_simples": e.anexo_simples,
        },
        "resultados": [r.__dict__ for r in resultados],
        "melhor_regime": melhor.regime,
        "resumo": (
            f"Com R$ {_brl(Decimal(e.receita_bruta_mensal))} por mês, o regime mais "
            f"vantajoso na simulação é {melhor.rotulo}, com líquido mensal de "
            f"R$ {melhor.liquido_mensal}. A diferença para o pior cenário "
            f"({pior.rotulo}) chega a R$ {diferenca_anual} por ano."
        ),
        "diferenca_anual_melhor_pior": diferenca_anual,
        "disclaimer": DISCLAIMER_SIMULADOR,
    }
