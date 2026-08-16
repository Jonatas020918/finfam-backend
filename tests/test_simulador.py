"""Testes do motor tributário — o cálculo é o coração do produto.

Os valores esperados são derivados das tabelas em `apps/simulators/rules.py`;
quando as tabelas forem atualizadas (virada de ano), estes testes falham de
propósito, sinalizando que os números publicados mudaram.
"""

from decimal import Decimal

import pytest

from apps.simulators import rules
from apps.simulators.services import (
    EntradaSimulacao,
    calcular_inss_clt,
    calcular_irpf_mensal,
    comparar_regimes,
    simular_autonomo,
    simular_clt,
    simular_pj,
)

D = Decimal


class TestINSS:
    def test_progressivo_na_primeira_faixa(self):
        # 1.000 × 7,5%
        assert calcular_inss_clt(D("1000")) == D("75.00")

    def test_soma_faixas_intermediarias(self):
        # 1.518×7,5% + (2.500−1.518)×9% = 113,85 + 88,38
        assert calcular_inss_clt(D("2500")) == D("202.23")

    def test_limita_no_teto(self):
        teto = calcular_inss_clt(rules.INSS_TETO_SALARIO_CONTRIBUICAO)
        assert calcular_inss_clt(D("50000")) == teto
        # O desconto máximo do empregado gira em torno de R$ 951 na tabela vigente.
        assert D("900") < teto < D("1000")


class TestIRPF:
    def test_isento_abaixo_do_limite(self):
        imposto, _ = calcular_irpf_mensal(D("2000"))
        assert imposto == D("0.00")

    def test_desconto_simplificado_vence_quando_maior(self):
        _, detalhe = calcular_irpf_mensal(D("10000"), dependentes=1)
        assert detalhe["modo_deducao"] == "desconto_simplificado"

    def test_deducoes_legais_vencem_com_muitos_dependentes(self):
        _, detalhe = calcular_irpf_mensal(D("10000"), dependentes=4)
        assert detalhe["modo_deducao"] == "deducoes_legais"

    def test_faixa_maxima(self):
        # (20.000 − 607,20) × 27,5% − 908,73 = 4.424,29
        imposto, _ = calcular_irpf_mensal(D("20000"))
        assert imposto == D("4424.29")

    def test_nunca_negativo(self):
        imposto, _ = calcular_irpf_mensal(D("2500"), dependentes=10)
        assert imposto == D("0.00")


class TestRegimes:
    def test_clt_desconta_inss_e_irpf(self):
        r = simular_clt(EntradaSimulacao(receita_bruta_mensal=D("30000")))
        assert r.inss_mensal == calcular_inss_clt(D("30000"))
        assert r.liquido_mensal == r.receita_bruta_mensal - r.inss_mensal - r.irpf_mensal
        # 13º e 1/3 de férias fazem o ano valer mais que 12 líquidos.
        assert r.liquido_anual > r.liquido_mensal * 12

    def test_clt_soma_beneficios_nao_tributaveis(self):
        base = simular_clt(EntradaSimulacao(receita_bruta_mensal=D("20000")))
        com_beneficio = simular_clt(
            EntradaSimulacao(
                receita_bruta_mensal=D("20000"),
                beneficios_nao_tributaveis_mensais=D("1500"),
            )
        )
        assert com_beneficio.liquido_mensal - base.liquido_mensal == D("1500.00")
        assert com_beneficio.irpf_mensal == base.irpf_mensal

    def test_pj_usa_anexo_iii_quando_fator_r_alcanca_28(self):
        r = simular_pj(EntradaSimulacao(receita_bruta_mensal=D("50000")))
        assert r.detalhes["anexo"] == "III"
        assert r.detalhes["fator_r"] >= D("0.28")

    def test_pj_cai_para_anexo_v_com_pro_labore_baixo(self):
        r = simular_pj(
            EntradaSimulacao(receita_bruta_mensal=D("50000"), pro_labore_mensal=D("2000"))
        )
        assert r.detalhes["anexo"] == "V"

    def test_pj_anexo_iii_e_mais_barato_que_anexo_v(self):
        entrada = dict(receita_bruta_mensal=D("50000"), pro_labore_mensal=D("14000"))
        iii = simular_pj(EntradaSimulacao(**entrada, anexo_simples="III"))
        v = simular_pj(EntradaSimulacao(**entrada, anexo_simples="V"))
        assert iii.liquido_mensal > v.liquido_mensal

    def test_pj_sem_pro_labore_gera_alerta_previdenciario(self):
        r = simular_pj(
            EntradaSimulacao(receita_bruta_mensal=D("40000"), pro_labore_mensal=D("0"))
        )
        assert r.inss_mensal == D("0.00")
        assert any("INSS" in a for a in r.alertas)

    def test_pj_desconta_despesas_operacionais(self):
        sem = simular_pj(EntradaSimulacao(receita_bruta_mensal=D("40000")))
        com = simular_pj(
            EntradaSimulacao(receita_bruta_mensal=D("40000"), despesas_pj_mensais=D("800"))
        )
        assert sem.liquido_mensal - com.liquido_mensal == D("800.00")

    def test_autonomo_deduz_livro_caixa_da_base_do_ir(self):
        sem = simular_autonomo(EntradaSimulacao(receita_bruta_mensal=D("30000")))
        com = simular_autonomo(
            EntradaSimulacao(
                receita_bruta_mensal=D("30000"), despesas_livro_caixa_mensais=D("5000")
            )
        )
        assert com.irpf_mensal < sem.irpf_mensal

    def test_autonomo_usa_11_por_cento_quando_retido_na_fonte(self):
        r = simular_autonomo(
            EntradaSimulacao(
                receita_bruta_mensal=D("30000"), inss_autonomo_retido_na_fonte=True
            )
        )
        esperado = rules.INSS_TETO_SALARIO_CONTRIBUICAO * rules.INSS_ALIQUOTA_PRO_LABORE
        assert r.inss_mensal == esperado.quantize(D("0.01"))

    def test_alerta_acima_do_limite_do_simples(self):
        r = simular_pj(EntradaSimulacao(receita_bruta_mensal=D("450000")))
        assert any("4,8 milhões" in a for a in r.alertas)


class TestComparacao:
    def test_pj_vence_em_renda_alta_de_medico(self):
        resultado = comparar_regimes(EntradaSimulacao(receita_bruta_mensal=D("50000")))
        assert resultado["melhor_regime"] == "pj"
        assert len(resultado["resultados"]) == 3

    def test_saida_traz_explicacao_e_disclaimer(self):
        """Requisito do modo self-service: número sem explicação não serve."""
        resultado = comparar_regimes(EntradaSimulacao(receita_bruta_mensal=D("35000")))
        assert resultado["disclaimer"]
        assert resultado["versao_regras"] == rules.VERSAO_REGRAS
        for regime in resultado["resultados"]:
            assert regime["explicacao"], f"{regime['regime']} sem explicação"

    def test_carga_efetiva_entre_zero_e_um(self):
        resultado = comparar_regimes(EntradaSimulacao(receita_bruta_mensal=D("25000")))
        for regime in resultado["resultados"]:
            assert D("0") <= regime["carga_tributaria_efetiva"] <= D("1")

    def test_receita_invalida_e_rejeitada(self):
        with pytest.raises(ValueError):
            EntradaSimulacao(receita_bruta_mensal=D("0"))
