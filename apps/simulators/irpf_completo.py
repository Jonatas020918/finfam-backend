"""Declaração de Ajuste Anual do IRPF — completa x simplificada, por regime.

`services.py` resolve a pergunta do dia a dia: CLT, PJ ou autônomo, qual dá
mais líquido no bolso este mês? Este módulo resolve uma pergunta diferente,
de fim de ano: vale mais detalhar cada dedução (dependentes, saúde, educação,
pensão alimentícia, previdência oficial e PGBL) ou usar o desconto
simplificado da Receita? É a pergunta que decide se vale a pena guardar
comprovante o ano inteiro.

CLT e PJ pedem entradas diferentes de propósito — pró-labore e lucro
distribuído não existem no holerite, e salário não existe na PJ — por isso
são duas funções (`simular_irpf_clt_anual` / `simular_irpf_pj_anual`) em vez
de uma comparação lado a lado como `comparar_regimes`.

Fora do escopo, de propósito:
  - 13º salário e o terço de férias têm tributação exclusiva na fonte, não
    entram na declaração de ajuste e por isso não entram nesta conta.
  - Lucros distribuídos da PJ são isentos hoje (mesma premissa de
    `services.simular_pj`) e não entram na base tributável.
  - Lucro Presumido/Real da pessoa jurídica é conta da empresa, não da pessoa
    física — fora do que esta simulação de IRPF pessoal resolve.

Mesmas regras de projeto de `services.py`: puro Python, sem banco/request;
toda saída explica o resultado em português simples; é simulação para
planejamento, não substitui contador.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from . import rules
from .rules import D
from .services import ZERO, _brl, calcular_inss_clt

DISCLAIMER_IRPF_COMPLETO = (
    "Simulação simplificada da declaração de ajuste anual, apenas para fins "
    "informativos e de planejamento. Não é recomendação de investimento, "
    "tributária ou contábil, não substitui a orientação de um contador, e não "
    "é uma declaração de imposto de renda válida perante a Receita Federal. "
    "Tetos e regras mudam a cada ano — confirme os valores vigentes."
)


@dataclass(frozen=True)
class DeducoesAnuais:
    """O que a pessoa contribuiu/gastou no ano — os métodos de dedução comuns
    a CLT e PJ na declaração de ajuste anual."""

    dependentes: int = 0
    saude: Decimal = ZERO
    educacao: Decimal = ZERO
    pessoas_com_educacao: int = 1
    pensao_alimenticia: Decimal = ZERO
    previdencia_privada_pgbl: Decimal = ZERO
    outras_deducoes_legais: Decimal = ZERO


@dataclass(frozen=True)
class EntradaIrpfCltAnual:
    salario_bruto_mensal: Decimal
    meses_trabalhados: int = 12
    deducoes: DeducoesAnuais = field(default_factory=DeducoesAnuais)


@dataclass(frozen=True)
class EntradaIrpfPjAnual:
    pro_labore_mensal: Decimal
    meses_trabalhados: int = 12
    outros_rendimentos_tributaveis_anuais: Decimal = ZERO
    deducoes: DeducoesAnuais = field(default_factory=DeducoesAnuais)


@dataclass
class ResultadoIrpfAnual:
    regime: str
    renda_bruta_tributavel_anual: Decimal
    inss_oficial_anual: Decimal
    limite_pgbl_anual: Decimal
    pgbl_considerado_anual: Decimal
    pgbl_excedente_nao_dedutivel: Decimal
    deducoes_detalhadas: dict
    total_deducoes_completa: Decimal
    imposto_declaracao_completa: Decimal
    imposto_declaracao_simplificada: Decimal
    desconto_simplificado_anual: Decimal
    modelo_mais_vantajoso: str
    economia_anual_pgbl: Decimal
    explicacao: list[str] = field(default_factory=list)
    alertas: list[str] = field(default_factory=list)


def _faixas_anuais() -> list[tuple[Decimal, Decimal, Decimal]]:
    """A tabela anual do IRPF é a tabela mensal × 12 — é assim que a Receita a define."""
    infinito = Decimal("Infinity")
    return [
        (teto if teto == infinito else teto * 12, aliquota, parcela * 12)
        for teto, aliquota, parcela in rules.IRPF_FAIXAS
    ]


def _imposto_anual_por_tabela(base: Decimal) -> Decimal:
    base = max(base, D("0"))
    for teto, aliquota, parcela in _faixas_anuais():
        if base <= teto:
            return max(base * aliquota - parcela, D("0"))
    return D("0")


def calcular_irpf_anual(
    regime: str,
    renda_bruta_tributavel_anual: Decimal,
    inss_oficial_anual: Decimal,
    deducoes: DeducoesAnuais,
) -> ResultadoIrpfAnual:
    renda = Decimal(renda_bruta_tributavel_anual)
    inss = Decimal(inss_oficial_anual)
    alertas: list[str] = []

    dependentes_anual = rules.IRPF_DEDUCAO_DEPENDENTE * 12 * deducoes.dependentes
    saude = Decimal(deducoes.saude)
    pensao = Decimal(deducoes.pensao_alimenticia)
    outras = Decimal(deducoes.outras_deducoes_legais)

    teto_educacao = rules.IRPF_TETO_EDUCACAO_ANUAL * max(deducoes.pessoas_com_educacao, 1)
    educacao_informada = Decimal(deducoes.educacao)
    educacao_considerada = min(educacao_informada, teto_educacao)
    educacao_excedente = max(educacao_informada - teto_educacao, D("0"))
    if educacao_excedente > 0:
        alertas.append(
            f"R$ {_brl(educacao_excedente)} de despesas com educação ficam fora do teto "
            f"legal (R$ {_brl(teto_educacao)} para {deducoes.pessoas_com_educacao} "
            "pessoa(s)) e não reduzem o imposto."
        )

    # PGBL só é dedutível para quem também contribui ao regime oficial — sem
    # INSS informado, o limite de 12% nem existe.
    limite_pgbl = renda * rules.PGBL_LIMITE_PERCENTUAL_RENDA_BRUTA if inss > 0 else D("0")
    pgbl_informado = Decimal(deducoes.previdencia_privada_pgbl)
    pgbl_considerado = min(pgbl_informado, limite_pgbl)
    pgbl_excedente = max(pgbl_informado - pgbl_considerado, D("0"))
    if inss <= 0 and pgbl_informado > 0:
        alertas.append(
            "O PGBL só é dedutível para quem também contribui ao INSS (ou a regime "
            f"próprio) — sem contribuição oficial nesta simulação, os R$ {_brl(pgbl_informado)} "
            "de PGBL informados não reduzem o imposto. VGBL nunca é dedutível, com ou "
            "sem INSS."
        )
    elif pgbl_excedente > 0:
        alertas.append(
            f"R$ {_brl(pgbl_excedente)} de PGBL ultrapassam o limite de 12% da renda "
            f"bruta (R$ {_brl(limite_pgbl)}) e não são dedutíveis. O excedente pode fazer "
            "mais sentido em VGBL — que não reduz o IR, mas também não tem esse teto."
        )

    total_deducoes = (
        dependentes_anual + saude + educacao_considerada + pensao
        + pgbl_considerado + inss + outras
    )

    base_completa = max(renda - total_deducoes, D("0"))
    imposto_completo = _brl(_imposto_anual_por_tabela(base_completa))

    desconto_simplificado = min(
        renda * rules.IRPF_DESCONTO_SIMPLIFICADO_ANUAL_PERCENTUAL,
        rules.IRPF_DESCONTO_SIMPLIFICADO_ANUAL_TETO,
    )
    base_simplificada = max(renda - desconto_simplificado, D("0"))
    imposto_simplificado = _brl(_imposto_anual_por_tabela(base_simplificada))

    # Imposto que sairia sem nenhum PGBL, para medir o efeito isolado dele —
    # a pergunta real de planejamento é "quanto eu economizo contribuindo".
    imposto_sem_pgbl = _brl(_imposto_anual_por_tabela(base_completa + pgbl_considerado))
    economia_pgbl = max(imposto_sem_pgbl - imposto_completo, D("0"))

    modelo = "completa" if imposto_completo <= imposto_simplificado else "simplificada"

    explicacao = [
        f"Pela declaração completa, suas deduções somam R$ {_brl(total_deducoes)} e o "
        f"imposto anual estimado é R$ {imposto_completo}.",
        f"Pela declaração simplificada, a Receita concede um desconto único de "
        f"R$ {_brl(desconto_simplificado)} (20% da renda, até o teto anual) e o imposto "
        f"estimado é R$ {imposto_simplificado}.",
        (
            f"Nesta simulação, a declaração {modelo} sai mais barata."
            if imposto_completo != imposto_simplificado
            else "Nesta simulação, as duas formas dão exatamente no mesmo imposto."
        ),
    ]
    if pgbl_considerado > 0:
        explicacao.append(
            f"O PGBL considerado (R$ {_brl(pgbl_considerado)}) reduz o imposto em cerca "
            f"de R$ {economia_pgbl} neste cenário — só compensa frente à declaração "
            "simplificada se essa economia superar o desconto único que você perderia."
        )

    return ResultadoIrpfAnual(
        regime=regime,
        renda_bruta_tributavel_anual=_brl(renda),
        inss_oficial_anual=_brl(inss),
        limite_pgbl_anual=_brl(limite_pgbl),
        pgbl_considerado_anual=_brl(pgbl_considerado),
        pgbl_excedente_nao_dedutivel=_brl(pgbl_excedente),
        deducoes_detalhadas={
            "dependentes": _brl(dependentes_anual),
            "saude": _brl(saude),
            "educacao_considerada": _brl(educacao_considerada),
            "educacao_excedente": _brl(educacao_excedente),
            "pensao_alimenticia": _brl(pensao),
            "pgbl_considerado": _brl(pgbl_considerado),
            "inss_oficial": _brl(inss),
            "outras": _brl(outras),
        },
        total_deducoes_completa=_brl(total_deducoes),
        imposto_declaracao_completa=imposto_completo,
        imposto_declaracao_simplificada=imposto_simplificado,
        desconto_simplificado_anual=_brl(desconto_simplificado),
        modelo_mais_vantajoso=modelo,
        economia_anual_pgbl=economia_pgbl,
        explicacao=explicacao,
        alertas=alertas,
    )


def simular_irpf_clt_anual(e: EntradaIrpfCltAnual) -> ResultadoIrpfAnual:
    salario = Decimal(e.salario_bruto_mensal)
    meses = e.meses_trabalhados
    renda_bruta_anual = salario * meses
    inss_anual = _brl(calcular_inss_clt(salario) * meses)

    resultado = calcular_irpf_anual("clt", renda_bruta_anual, inss_anual, e.deducoes)
    resultado.explicacao.insert(
        0,
        f"Esta simulação considera só o salário regular dos {meses} meses trabalhados "
        "— 13º salário e o terço de férias têm tributação exclusiva na fonte e não "
        "entram nesta conta nem na comparação entre declaração completa e simplificada.",
    )
    return resultado


def simular_irpf_pj_anual(e: EntradaIrpfPjAnual) -> ResultadoIrpfAnual:
    pro_labore = Decimal(e.pro_labore_mensal)
    meses = e.meses_trabalhados
    renda_bruta_anual = pro_labore * meses + Decimal(e.outros_rendimentos_tributaveis_anuais)
    base_inss = min(pro_labore, rules.INSS_TETO_SALARIO_CONTRIBUICAO)
    inss_anual = _brl(base_inss * rules.INSS_ALIQUOTA_PRO_LABORE) * meses

    resultado = calcular_irpf_anual("pj", renda_bruta_anual, inss_anual, e.deducoes)
    resultado.explicacao.insert(
        0,
        "Esta simulação tributa apenas o pró-labore (mais outros rendimentos "
        "tributáveis informados) — lucros distribuídos da sua PJ hoje são isentos de "
        "IR na pessoa física e ficam fora desta conta.",
    )
    if pro_labore <= 0:
        resultado.alertas.append(
            "Sem pró-labore não há contribuição ao INSS nem base para o PGBL ser "
            "dedutível — vale reavaliar essa estrutura com seu contador."
        )
    return resultado
