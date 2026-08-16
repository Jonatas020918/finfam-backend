"""Motor de amortização: Price, SAC e simulação de quitação antecipada.

Os valores esperados vêm da matemática financeira padrão, não da implementação:
se o cálculo mudar, estes testes acusam.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.simulators.amortizacao import (
    EstrategiaAporte,
    gerar_cronograma,
    parcela_price,
    simular_amortizacao,
)

D = Decimal


class TestParcelaPrice:
    def test_formula_conhecida(self):
        # 100.000 em 120x a 1% a.m. ⇒ PMT ≈ 1.434,71
        assert parcela_price(D("100000"), D("0.01"), 120) == D("1434.71")

    def test_sem_juros_divide_igualmente(self):
        assert parcela_price(D("12000"), D("0"), 12) == D("1000.00")

    def test_prazo_invalido_nao_quebra(self):
        assert parcela_price(D("10000"), D("0.01"), 0) == D("0.00")


class TestCronogramaPrice:
    def test_quita_no_prazo_contratado(self):
        cenario = gerar_cronograma(D("100000"), D("0.01"), 120)
        assert cenario.parcelas_restantes == 120
        assert cenario.cronograma[-1].saldo_final == D("0.00")

    def test_parcela_e_fixa(self):
        cenario = gerar_cronograma(D("100000"), D("0.01"), 120)
        valores = {p.valor for p in cenario.cronograma[:-1]}
        assert len(valores) == 1

    def test_juros_caem_e_amortizacao_sobe(self):
        """A assinatura do Price: no início quase tudo é juro."""
        cenario = gerar_cronograma(D("100000"), D("0.01"), 120)
        primeira, ultima = cenario.cronograma[0], cenario.cronograma[-1]
        assert primeira.juros > primeira.amortizacao
        assert ultima.amortizacao > ultima.juros

    def test_total_de_juros_e_a_diferenca_do_principal(self):
        cenario = gerar_cronograma(D("100000"), D("0.01"), 120)
        assert cenario.total_juros == pytest.approx(
            cenario.total_pago - D("100000"), abs=D("1.00")
        )


class TestCronogramaSac:
    def test_amortizacao_constante(self):
        cenario = gerar_cronograma(D("120000"), D("0.008"), 120, sistema="sac")
        amortizacoes = {p.amortizacao for p in cenario.cronograma}
        assert amortizacoes == {D("1000.00")}

    def test_parcela_decrescente(self):
        cenario = gerar_cronograma(D("120000"), D("0.008"), 120, sistema="sac")
        assert cenario.primeira_parcela > cenario.ultima_parcela

    def test_sac_paga_menos_juros_que_price(self):
        sac = gerar_cronograma(D("120000"), D("0.008"), 120, sistema="sac")
        price = gerar_cronograma(D("120000"), D("0.008"), 120, sistema="price")
        assert sac.total_juros < price.total_juros


class TestAporteExtra:
    def test_aporte_mensal_antecipa_a_quitacao(self):
        sem = gerar_cronograma(D("100000"), D("0.01"), 120)
        com = gerar_cronograma(
            D("100000"), D("0.01"), 120, aporte_extra_mensal=D("500")
        )
        assert com.parcelas_restantes < sem.parcelas_restantes
        assert com.total_juros < sem.total_juros

    def test_aporte_unico_abate_saldo_antes_da_primeira_parcela(self):
        com = gerar_cronograma(D("100000"), D("0.01"), 120, aporte_unico=D("20000"))
        # Juros do primeiro mês incidem sobre 80.000, não sobre 100.000.
        assert com.cronograma[0].juros == D("800.00")

    def test_aporte_unico_maior_que_o_saldo_quita_o_contrato(self):
        cenario = gerar_cronograma(D("10000"), D("0.01"), 24, aporte_unico=D("10000"))
        assert cenario.parcelas_restantes == 0

    def test_reduzir_prazo_economiza_mais_juros_que_reduzir_parcela(self):
        prazo = gerar_cronograma(
            D("100000"), D("0.01"), 120,
            aporte_extra_mensal=D("500"),
            estrategia=EstrategiaAporte.REDUZIR_PRAZO,
        )
        parcela = gerar_cronograma(
            D("100000"), D("0.01"), 120,
            aporte_extra_mensal=D("500"),
            estrategia=EstrategiaAporte.REDUZIR_PARCELA,
        )
        assert prazo.total_juros < parcela.total_juros

    def test_reduzir_parcela_alivia_o_mes(self):
        cenario = gerar_cronograma(
            D("100000"), D("0.01"), 120,
            aporte_extra_mensal=D("500"),
            estrategia=EstrategiaAporte.REDUZIR_PARCELA,
        )
        # A parcela contratual cai ao longo do tempo (fora o aporte).
        contratual_inicio = cenario.cronograma[0].valor - cenario.cronograma[0].amortizacao_extra
        contratual_fim = cenario.cronograma[-2].valor - cenario.cronograma[-2].amortizacao_extra
        assert contratual_fim < contratual_inicio


class TestSimulacaoCompleta:
    def test_posicao_do_contrato(self):
        resultado = simular_amortizacao(
            saldo_devedor=D("240000"),
            taxa_mensal_percentual=D("0.9"),
            parcelas_restantes=180,
            parcelas_pagas=60,
            parcelas_totais=240,
            referencia=date(2026, 8, 1),
        )
        posicao = resultado["posicao"]
        assert posicao["parcelas_pagas"] == 60
        assert posicao["parcelas_restantes"] == 180
        assert posicao["progresso_percentual"] == D("25.00")
        # 180 meses a partir de agosto/2026 ⇒ agosto/2041.
        assert posicao["quitacao_prevista"] == date(2041, 8, 1)

    def test_sem_aporte_nao_ha_cenario_alternativo(self):
        resultado = simular_amortizacao(
            saldo_devedor=D("50000"), taxa_mensal_percentual=D("1.2"), parcelas_restantes=36
        )
        assert resultado["cenario_com_aporte"] is None
        assert resultado["economia"] is None

    def test_economia_em_meses_e_juros(self):
        resultado = simular_amortizacao(
            saldo_devedor=D("240000"),
            taxa_mensal_percentual=D("0.9"),
            parcelas_restantes=180,
            aporte_extra_mensal=D("1000"),
            referencia=date(2026, 8, 1),
        )
        economia = resultado["economia"]
        assert economia["meses"] > 0
        assert economia["juros"] > 0
        assert economia["nova_quitacao"] < resultado["posicao"]["quitacao_prevista"]
        assert "ano" in economia["anos_texto"]

    def test_disclaimer_sempre_presente(self):
        resultado = simular_amortizacao(
            saldo_devedor=D("10000"), taxa_mensal_percentual=D("1"), parcelas_restantes=12
        )
        assert "seguro" in resultado["disclaimer"]


@pytest.mark.django_db
class TestAmortizacaoViaAPI:
    def _criar_divida(self, api, **campos):
        payload = {
            "tipo": "financiamento_imovel",
            "descricao": "Apartamento",
            "saldo_devedor": "240000",
            "taxa_juros_mensal": "0.9",
            "parcelas_restantes": 180,
            "parcelas_totais": 240,
            "valor_parcela": "2600",
            "sistema": "sac",
            **campos,
        }
        return api.post(reverse("divida-list"), payload, format="json")

    def test_simula_a_partir_de_divida_cadastrada(self, api, familia_autenticada):
        divida = self._criar_divida(api).data

        resposta = api.post(
            reverse("simulador-amortizacao"),
            {"divida": divida["id"], "aporte_extra_mensal": "1000"},
            format="json",
        )

        assert resposta.status_code == 200, resposta.data
        assert resposta.data["sistema"] == "sac"
        assert resposta.data["divida"]["descricao"] == "Apartamento"
        assert resposta.data["economia"]["meses"] > 0

    def test_calcula_parcelas_pagas_pela_data_da_primeira(self, api, familia_autenticada):
        """Com a data do contrato, o progresso não depende de o cliente atualizar."""
        hoje = date.today()
        # Primeira parcela há exatamente 5 anos, no dia 1º: 60 meses decorridos
        # + a parcela deste mês, que já venceu ⇒ 61 pagas.
        primeira = date(hoje.year - 5, hoje.month, 1)
        divida = self._criar_divida(
            api, data_primeira_parcela=primeira.isoformat(), parcelas_totais=240
        ).data

        assert divida["parcelas_pagas"] == 61
        assert divida["parcelas_a_pagar"] == 179
        assert Decimal(divida["progresso_percentual"]) == D("25.42")

        # Última das 240 parcelas: 239 meses depois da primeira.
        ano_final = primeira.year + (primeira.month - 1 + 239) // 12
        mes_final = (primeira.month - 1 + 239) % 12 + 1
        assert divida["data_quitacao_prevista"] == date(ano_final, mes_final, 1).isoformat()

    def test_simula_sem_divida_cadastrada(self, api, familia_autenticada):
        resposta = api.post(
            reverse("simulador-amortizacao"),
            {
                "saldo_devedor": "60000",
                "taxa_juros_mensal": "1.5",
                "parcelas_restantes": 48,
                "sistema": "price",
                "aporte_unico": "10000",
            },
            format="json",
        )
        assert resposta.status_code == 200
        assert resposta.data["economia"]["meses"] > 0

    def test_exige_dados_quando_nao_ha_divida(self, api, familia_autenticada):
        resposta = api.post(reverse("simulador-amortizacao"), {}, format="json")
        assert resposta.status_code == 400
        assert "saldo_devedor" in resposta.data

    def test_nao_simula_divida_de_outro_nucleo(self, api, familia, familia_autenticada):
        outra_household, _, _ = familia(
            email="outro@exemplo.com", nome="Outro", nome_familia="Família B"
        )
        from apps.households.models import Debt

        divida_alheia = Debt.objects.create(
            tenant=outra_household.tenant,
            household=outra_household,
            tipo="cartao",
            descricao="Dívida alheia",
            saldo_devedor=D("5000"),
            taxa_juros_mensal=D("12"),
            parcelas_restantes=10,
        )

        resposta = api.post(
            reverse("simulador-amortizacao"),
            {"divida": str(divida_alheia.id)},
            format="json",
        )
        assert resposta.status_code == 404
