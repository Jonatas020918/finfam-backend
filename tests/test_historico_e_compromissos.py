"""Duas perguntas que a plataforma sabia responder e não respondia.

Todas as telas eram mensais, mas as decisões que o produto promete apoiar —
trocar de regime, antecipar financiamento, definir quanto guardar — se tomam
olhando o ano. E quem acabava de assumir cinco anos de parcela não tinha onde
ver o tamanho do compromisso: a parcela só aparecia no mês dela, um por vez.
"""

from datetime import date
from decimal import Decimal as D

import pytest
from django.urls import reverse

from apps.cashflow.models import CashFlowEntry, RecurringExpense
from apps.cashflow.services import compromissos_assumidos, historico_consolidado
from apps.households.models import Debt

pytestmark = pytest.mark.django_db


def _lancar(household, ano, mes, receita, despesa):
    if receita:
        CashFlowEntry.objects.create(
            household=household, tenant=household.tenant, ano=ano, mes=mes,
            tipo="receita", categoria="renda_trabalho", descricao="Renda",
            valor_realizado=D(receita),
        )
    if despesa:
        CashFlowEntry.objects.create(
            household=household, tenant=household.tenant, ano=ano, mes=mes,
            tipo="despesa", categoria="despesa_fixa", descricao="Custos",
            valor_realizado=D(despesa),
        )


class TestHistoricoConsolidado:
    def test_soma_o_periodo_e_calcula_a_media(self, familia_autenticada):
        household, _, _ = familia_autenticada
        _lancar(household, 2026, 7, "10000", "4000")
        _lancar(household, 2026, 8, "20000", "6000")

        h = historico_consolidado(household, 2026, 8, meses=2)

        assert h["receitas"] == D("30000")
        assert h["despesas"] == D("10000")
        assert h["saldo"] == D("20000")
        assert h["media_receitas"] == D("15000.00")

    def test_aponta_o_melhor_e_o_pior_mes(self, familia_autenticada):
        """É o que a média esconde — e é nele que o aperto acontece."""
        household, _, _ = familia_autenticada
        _lancar(household, 2026, 7, "10000", "9000")
        _lancar(household, 2026, 8, "20000", "5000")

        h = historico_consolidado(household, 2026, 8, meses=2)

        assert h["melhor_mes"]["mes"] == 8
        assert h["pior_mes"]["mes"] == 7

    def test_mes_vazio_nao_puxa_a_media_para_baixo(self, familia_autenticada):
        """Quem começou a usar em agosto não tem julho ruim: tem julho vazio.

        Incluir mês sem lançamento na média faria a plataforma dizer que a
        pessoa ganha metade do que ganha.
        """
        household, _, _ = familia_autenticada
        _lancar(household, 2026, 8, "20000", "5000")

        h = historico_consolidado(household, 2026, 8, meses=12)

        assert h["meses_com_movimento"] == 1
        assert h["media_receitas"] == D("20000.00")
        assert len(h["meses"]) == 12

    def test_atravessa_a_virada_do_ano(self, familia_autenticada):
        household, _, _ = familia_autenticada
        _lancar(household, 2025, 12, "5000", "1000")
        _lancar(household, 2026, 1, "7000", "2000")

        h = historico_consolidado(household, 2026, 1, meses=2)

        assert h["de"] == {"ano": 2025, "mes": 12}
        assert h["receitas"] == D("12000")

    def test_pdf_do_periodo_sai_como_arquivo(self, api, familia_autenticada):
        household, _, _ = familia_autenticada
        _lancar(household, 2026, 8, "20000", "5000")

        resposta = api.get(reverse("historico-fluxo"), {"ano": 2026, "mes": 8, "meses": 12})

        assert resposta.status_code == 200
        assert resposta["Content-Type"] == "application/pdf"
        assert "fluxo-de-caixa-12-meses" in resposta["Content-Disposition"]


class TestCompromissosAssumidos:
    def _divida_com_parcela(self, household, **extras):
        divida = Debt.objects.create(
            household=household, tenant=household.tenant, tipo="financiamento_veiculo",
            descricao="Carro", saldo_devedor=D("50000"), valor_parcela=D("1573"),
            parcelas_totais=60, data_primeira_parcela=date(2026, 10, 9), **extras,
        )
        RecurringExpense.objects.create(
            household=household, tenant=household.tenant, divida=divida,
            descricao=divida.descricao, categoria="divida", valor_previsto=D("1573"),
            vigencia_inicio=date(2026, 10, 9), vigencia_fim=date(2031, 9, 1), ativa=True,
        )
        return divida

    def test_mostra_o_que_sai_por_mes_e_quanto_falta(self, familia_autenticada):
        household, _, _ = familia_autenticada
        self._divida_com_parcela(household)

        c = compromissos_assumidos(household, referencia=date(2026, 8, 24))

        assert c["total_mensal"] == D("1573")
        assert len(c["itens"]) == 1
        item = c["itens"][0]
        assert item["parcelas_restantes"] == 60
        assert item["total_restante"] == D("94380")
        assert item["ja_comecou"] is False

    def test_diz_quando_o_orcamento_alivia(self, familia_autenticada):
        household, _, _ = familia_autenticada
        self._divida_com_parcela(household)

        c = compromissos_assumidos(household, referencia=date(2026, 8, 24))

        assert c["livre_em"] == date(2031, 9, 1)

    def test_compromisso_ja_encerrado_sai_da_conta(self, familia_autenticada):
        """Parcela que acabou não é compromisso — mantê-la aqui assustaria à toa."""
        household, _, _ = familia_autenticada
        divida = self._divida_com_parcela(household)
        RecurringExpense.objects.filter(divida=divida).update(
            vigencia_inicio=date(2020, 1, 1), vigencia_fim=date(2024, 1, 1)
        )

        c = compromissos_assumidos(household, referencia=date(2026, 8, 24))

        assert c["itens"] == []
        assert c["total_mensal"] == D("0.00")

    def test_rotativo_admite_que_nao_sabe_quando_acaba(self, familia_autenticada):
        """Cartão não tem prazo. Inventar um número seria pior que dizer que
        não se sabe."""
        household, _, _ = familia_autenticada
        divida = self._divida_com_parcela(household)
        RecurringExpense.objects.filter(divida=divida).update(vigencia_fim=None)

        c = compromissos_assumidos(household, referencia=date(2026, 8, 24))

        assert c["itens"][0]["parcelas_restantes"] is None
        assert c["algum_sem_fim"] is True

    def test_endpoint_responde_para_a_tela(self, api, familia_autenticada):
        household, _, _ = familia_autenticada
        self._divida_com_parcela(household)

        dados = api.get(reverse("lancamento-compromissos")).data

        assert D(str(dados["total_mensal"])) == D("1573")
        assert len(dados["itens"]) == 1
