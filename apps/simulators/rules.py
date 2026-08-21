"""Parâmetros tributários usados pelo simulador PJ x CLT x Autônomo.

IMPORTANTE
----------
Estes valores mudam por lei/portaria (tipicamente em janeiro e/ou maio). Eles
ficam isolados aqui, versionados por `VERSAO_REGRAS`, para que a atualização
anual seja uma alteração de dados — nunca de lógica. Toda simulação persistida
guarda a versão usada (`SimulationRun.versao_regras`), de modo que um resultado
antigo continue explicável mesmo depois de uma atualização.

Antes de cada virada de ano, conferir:
  - Tabela do INSS (empregado e contribuinte individual) e o teto
  - Tabela mensal do IRPF, deduções e o desconto simplificado
  - Anexos III/V do Simples Nacional
  - Tributação de lucros distribuídos (ver IR_DIVIDENDOS_PERCENTUAL)

Fontes: Receita Federal (tabelas IRPF/Simples), Portaria interministerial do
INSS, Lei Complementar 123/2006 (anexos).
"""

from decimal import Decimal

VERSAO_REGRAS = "2025.1"
ANO_REFERENCIA = 2025

D = Decimal


# --- INSS ------------------------------------------------------------------

# Faixas progressivas do empregado CLT: (teto da faixa, alíquota)
INSS_FAIXAS_CLT: list[tuple[Decimal, Decimal]] = [
    (D("1518.00"), D("0.075")),
    (D("2793.88"), D("0.09")),
    (D("4190.83"), D("0.12")),
    (D("8157.41"), D("0.14")),
]
INSS_TETO_SALARIO_CONTRIBUICAO = D("8157.41")

# Contribuinte individual (autônomo e pró-labore de sócio):
# 20% sobre o salário de contribuição, limitado ao teto. Quando há desconto na
# fonte pela empresa tomadora, a alíquota do segurado é 11%.
INSS_ALIQUOTA_CONTRIBUINTE_INDIVIDUAL = D("0.20")
INSS_ALIQUOTA_PRO_LABORE = D("0.11")
INSS_PATRONAL_PRO_LABORE = D("0.20")


# --- IRPF (tabela mensal) --------------------------------------------------

# (teto da faixa, alíquota, parcela a deduzir)
IRPF_FAIXAS: list[tuple[Decimal, Decimal, Decimal]] = [
    (D("2428.80"), D("0.00"), D("0.00")),
    (D("2826.65"), D("0.075"), D("182.16")),
    (D("3751.05"), D("0.15"), D("394.16")),
    (D("4664.68"), D("0.225"), D("675.49")),
    (Decimal("Infinity"), D("0.275"), D("908.73")),
]
IRPF_DEDUCAO_DEPENDENTE = D("189.59")
IRPF_DESCONTO_SIMPLIFICADO = D("607.20")


# --- Simples Nacional ------------------------------------------------------

# (teto de RBT12, alíquota nominal, parcela a deduzir)
SIMPLES_ANEXO_III: list[tuple[Decimal, Decimal, Decimal]] = [
    (D("180000"), D("0.06"), D("0")),
    (D("360000"), D("0.112"), D("9360")),
    (D("720000"), D("0.135"), D("17640")),
    (D("1800000"), D("0.16"), D("35640")),
    (D("3600000"), D("0.21"), D("125640")),
    (D("4800000"), D("0.33"), D("648000")),
]

SIMPLES_ANEXO_V: list[tuple[Decimal, Decimal, Decimal]] = [
    (D("180000"), D("0.155"), D("0")),
    (D("360000"), D("0.18"), D("4500")),
    (D("720000"), D("0.195"), D("9900")),
    (D("1800000"), D("0.205"), D("17100")),
    (D("3600000"), D("0.23"), D("62100")),
    (D("4800000"), D("0.305"), D("540000")),
]

# Serviços médicos migram do Anexo V para o III quando o Fator R
# (folha 12 meses ÷ receita bruta 12 meses) alcança 28%.
FATOR_R_LIMITE = D("0.28")

# Encargos sobre a folha do pró-labore no Simples (CPP já está incluída no DAS
# dos anexos III/V, então aqui entra apenas o INSS patronal quando aplicável).
SIMPLES_CPP_INCLUSA_NO_DAS = True

# Distribuição de lucros: historicamente isenta na pessoa física. Mantido como
# parâmetro porque é o ponto do cálculo mais sujeito a mudança legislativa —
# alterar aqui já reflete em todas as simulações novas.
IR_DIVIDENDOS_PERCENTUAL = D("0.00")


# --- CLT: verbas anuais ----------------------------------------------------

# 13º salário + 1/3 constitucional de férias ⇒ 13,333 salários/ano.
CLT_SALARIOS_POR_ANO = D("13.3333")
FGTS_PERCENTUAL = D("0.08")


# --- IRPF: declaração de ajuste anual ---------------------------------------
#
# O desconto simplificado da declaração ANUAL é um mecanismo diferente do
# desconto simplificado MENSAL (`IRPF_DESCONTO_SIMPLIFICADO`, usado na
# retenção na fonte, acima): na declaração anual vale 20% da renda bruta
# tributável, limitado a este teto — não é o valor mensal vezes 12.
IRPF_DESCONTO_SIMPLIFICADO_ANUAL_PERCENTUAL = D("0.20")
IRPF_DESCONTO_SIMPLIFICADO_ANUAL_TETO = D("16754.34")

# Educação: teto de dedução por pessoa (titular ou dependente), ao ano. Saúde
# e pensão alimentícia não têm teto legal — só educação e PGBL têm.
IRPF_TETO_EDUCACAO_ANUAL = D("3561.50")

# Previdência privada PGBL: dedutível até este percentual da renda bruta
# tributável anual, e só para quem também contribui ao regime oficial (RGPS
# ou RPPS). VGBL não é dedutível em nenhuma hipótese — é a confusão mais
# comum entre os dois produtos.
PGBL_LIMITE_PERCENTUAL_RENDA_BRUTA = D("0.12")


def faixa_progressiva(base: Decimal, faixas: list[tuple[Decimal, Decimal]]) -> Decimal:
    """Soma o imposto faixa a faixa (usado pelo INSS do empregado CLT)."""
    total = D("0")
    piso = D("0")
    for teto, aliquota in faixas:
        if base <= piso:
            break
        tributavel = min(base, teto) - piso
        total += tributavel * aliquota
        piso = teto
    return total


def aliquota_efetiva_simples(rbt12: Decimal, anexo: list[tuple[Decimal, Decimal, Decimal]]) -> Decimal:
    """Alíquota efetiva do Simples: (RBT12 × alíquota nominal − dedução) ÷ RBT12."""
    if rbt12 <= 0:
        return D("0")
    for teto, nominal, deducao in anexo:
        if rbt12 <= teto:
            efetiva = (rbt12 * nominal - deducao) / rbt12
            return max(efetiva, D("0"))
    # Acima do limite do Simples (R$ 4,8 mi) — usa a última faixa como piso e
    # sinaliza pela alíquota alta; o desenquadramento é tratado no serviço.
    teto, nominal, deducao = anexo[-1]
    return (rbt12 * nominal - deducao) / rbt12
