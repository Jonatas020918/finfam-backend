"""Testes do simulador de declaração de ajuste anual (IRPF completo).

Os valores esperados são calculados à mão a partir das tabelas em
`apps/simulators/rules.py` (tabela mensal × 12, teto/percentual do desconto
simplificado anual, teto de educação, limite de PGBL). Quando as tabelas
mudarem, estes testes falham de propósito.
"""

from decimal import Decimal

from apps.simulators import rules
from apps.simulators.irpf_completo import (
    DeducoesAnuais,
    EntradaIrpfCltAnual,
    EntradaIrpfPjAnual,
    calcular_inss_clt,
    simular_irpf_clt_anual,
    simular_irpf_pj_anual,
)

D = Decimal


class TestIrpfCltAnual:
    def test_sem_deducoes_extras_compara_completa_e_simplificada(self):
        r = simular_irpf_clt_anual(EntradaIrpfCltAnual(salario_bruto_mensal=D("20000")))

        assert r.renda_bruta_tributavel_anual == D("240000.00")
        assert r.inss_oficial_anual == calcular_inss_clt(D("20000")) * 12
        # (240.000 − 11.419,56) × 27,5% − 10.904,76
        assert r.imposto_declaracao_completa == D("51954.86")
        # desconto simplificado anual = min(20% de 240.000, teto) = teto
        assert r.desconto_simplificado_anual == rules.IRPF_DESCONTO_SIMPLIFICADO_ANUAL_TETO
        assert r.imposto_declaracao_simplificada == D("50487.80")
        assert r.modelo_mais_vantajoso == "simplificada"

    def test_13o_salario_fica_fora_da_conta(self):
        r = simular_irpf_clt_anual(EntradaIrpfCltAnual(salario_bruto_mensal=D("20000")))
        assert any("13º" in e for e in r.explicacao)

    def test_pgbl_dentro_do_limite_reduz_o_imposto_na_aliquota_marginal(self):
        base = simular_irpf_clt_anual(EntradaIrpfCltAnual(salario_bruto_mensal=D("20000")))
        com_pgbl = simular_irpf_clt_anual(
            EntradaIrpfCltAnual(
                salario_bruto_mensal=D("20000"),
                deducoes=DeducoesAnuais(previdencia_privada_pgbl=D("20000")),
            )
        )

        assert com_pgbl.pgbl_considerado_anual == D("20000.00")
        assert com_pgbl.pgbl_excedente_nao_dedutivel == D("0.00")
        # Ambas as bases caem na última faixa (27,5%): a economia é exatamente
        # o valor do PGBL multiplicado pela alíquota marginal.
        assert com_pgbl.economia_anual_pgbl == D("20000") * D("0.275")
        assert com_pgbl.imposto_declaracao_completa < base.imposto_declaracao_completa

    def test_pgbl_acima_do_limite_gera_excedente_e_alerta(self):
        r = simular_irpf_clt_anual(
            EntradaIrpfCltAnual(
                salario_bruto_mensal=D("10000"),
                deducoes=DeducoesAnuais(previdencia_privada_pgbl=D("20000")),
            )
        )
        # limite = 12% de 120.000 = 14.400
        assert r.limite_pgbl_anual == D("14400.00")
        assert r.pgbl_considerado_anual == D("14400.00")
        assert r.pgbl_excedente_nao_dedutivel == D("5600.00")
        assert any("ultrapassam o limite" in a for a in r.alertas)

    def test_educacao_acima_do_teto_gera_excedente_e_alerta(self):
        r = simular_irpf_clt_anual(
            EntradaIrpfCltAnual(
                salario_bruto_mensal=D("20000"),
                deducoes=DeducoesAnuais(educacao=D("10000"), pessoas_com_educacao=2),
            )
        )
        teto = rules.IRPF_TETO_EDUCACAO_ANUAL * 2
        assert r.deducoes_detalhadas["educacao_considerada"] == teto
        assert r.deducoes_detalhadas["educacao_excedente"] == D("10000") - teto
        assert any("educação" in a for a in r.alertas)

    def test_saude_e_pensao_nao_tem_teto(self):
        sem = simular_irpf_clt_anual(EntradaIrpfCltAnual(salario_bruto_mensal=D("20000")))
        com = simular_irpf_clt_anual(
            EntradaIrpfCltAnual(
                salario_bruto_mensal=D("20000"),
                deducoes=DeducoesAnuais(saude=D("50000"), pensao_alimenticia=D("50000")),
            )
        )
        assert com.total_deducoes_completa - sem.total_deducoes_completa == D("100000.00")

    def test_dependentes_aumentam_a_deducao_legal(self):
        sem = simular_irpf_clt_anual(EntradaIrpfCltAnual(salario_bruto_mensal=D("15000")))
        com = simular_irpf_clt_anual(
            EntradaIrpfCltAnual(
                salario_bruto_mensal=D("15000"), deducoes=DeducoesAnuais(dependentes=2)
            )
        )
        esperado = rules.IRPF_DEDUCAO_DEPENDENTE * 12 * 2
        assert com.total_deducoes_completa - sem.total_deducoes_completa == esperado


class TestIrpfPjAnual:
    def test_tributa_so_o_pro_labore(self):
        r = simular_irpf_pj_anual(
            EntradaIrpfPjAnual(
                pro_labore_mensal=D("15000"), deducoes=DeducoesAnuais(dependentes=1)
            )
        )
        assert r.renda_bruta_tributavel_anual == D("180000.00")
        # INSS: 11% sobre o teto de contribuição (pró-labore acima do teto)
        assert r.inss_oficial_anual == D("897.32") * 12
        assert r.imposto_declaracao_completa == D("35008.44")
        assert r.imposto_declaracao_simplificada == D("33987.80")
        assert r.modelo_mais_vantajoso == "simplificada"
        assert any("lucros distribuídos" in e for e in r.explicacao)

    def test_outros_rendimentos_somam_na_base(self):
        sem = simular_irpf_pj_anual(EntradaIrpfPjAnual(pro_labore_mensal=D("15000")))
        com = simular_irpf_pj_anual(
            EntradaIrpfPjAnual(
                pro_labore_mensal=D("15000"),
                outros_rendimentos_tributaveis_anuais=D("24000"),
            )
        )
        assert com.renda_bruta_tributavel_anual - sem.renda_bruta_tributavel_anual == D("24000.00")

    def test_sem_pro_labore_barra_o_pgbl_e_gera_dois_alertas(self):
        r = simular_irpf_pj_anual(
            EntradaIrpfPjAnual(
                pro_labore_mensal=D("0"),
                outros_rendimentos_tributaveis_anuais=D("100000"),
                deducoes=DeducoesAnuais(previdencia_privada_pgbl=D("5000")),
            )
        )
        assert r.inss_oficial_anual == D("0.00")
        assert r.limite_pgbl_anual == D("0.00")
        assert r.pgbl_considerado_anual == D("0.00")
        assert r.pgbl_excedente_nao_dedutivel == D("5000.00")
        assert any("PGBL só é dedutível" in a for a in r.alertas)
        assert any("Sem pró-labore" in a for a in r.alertas)


class TestDisclaimer:
    def test_todo_resultado_tem_explicacao(self):
        r = simular_irpf_clt_anual(EntradaIrpfCltAnual(salario_bruto_mensal=D("12000")))
        assert r.explicacao
