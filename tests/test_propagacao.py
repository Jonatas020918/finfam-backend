"""Alterar um cadastro fixo reflete nos meses ainda em aberto.

Sem isso, mudar o salário no cadastro deixava o mês corrente com o valor antigo
— e o usuário via um número desatualizado sem entender por quê.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.cashflow.competencia import abrir_competencia
from apps.cashflow.models import CashFlowEntry

pytestmark = pytest.mark.django_db

D = Decimal


def _competencia_atual():
    hoje = date.today()
    return hoje.year, hoje.month


def _mes_anterior():
    hoje = date.today()
    return (hoje.year - 1, 12) if hoje.month == 1 else (hoje.year, hoje.month - 1)


@pytest.fixture
def cadastros(api, familia_autenticada):
    """Salário fixo e aluguel recorrente, já materializados no mês corrente."""
    household, titular, _ = familia_autenticada
    ano, mes = _competencia_atual()

    fonte = api.post(
        reverse("fonte-renda-list"),
        {
            "membro": str(titular.id),
            "descricao": "Salário do hospital",
            "tipo": "clt_hospitalar",
            "regime": "clt",
            "valor_medio_mensal": "18000",
            "modo_lancamento": "fixa",
            # Este teste verifica materialização/propagação, não o motor de
            # imposto — que tem suíte própria em test_liquido_e_parcelas.py.
            # Sem isto, o valor sofreria retenção e a asserção pararia de
            # bater com o número digitado.
            "valor_e_bruto": False,
        },
        format="json",
    ).data

    despesa = api.post(
        reverse("despesa-fixa-list"),
        {
            "descricao": "Aluguel",
            "categoria": "despesa_fixa",
            "valor_previsto": "8000",
            "vigencia_inicio": "2020-01-01",
        },
        format="json",
    ).data

    api.post(reverse("abrir-competencia"), {"ano": ano, "mes": mes}, format="json")
    return household, fonte, despesa


class TestReceitaFixa:
    def test_novo_valor_chega_ao_mes_corrente(self, api, cadastros):
        _, fonte, _ = cadastros
        ano, mes = _competencia_atual()

        api.patch(
            reverse("fonte-renda-detail", args=[fonte["id"]]),
            {"valor_medio_mensal": "21000"},
            format="json",
        )

        resumo = api.get(reverse("lancamento-resumo"), {"ano": ano, "mes": mes}).data
        assert D(resumo["receitas_realizadas"]) == D("21000.00")

    def test_renomear_acompanha_o_lancamento(self, api, cadastros):
        _, fonte, _ = cadastros
        ano, mes = _competencia_atual()

        api.patch(
            reverse("fonte-renda-detail", args=[fonte["id"]]),
            {"descricao": "Salário — Hospital Central"},
            format="json",
        )

        lancamento = CashFlowEntry.objects.get(ano=ano, mes=mes, tipo="receita")
        assert lancamento.descricao == "Salário — Hospital Central"

    def test_mudanca_de_vinculo_alimenta_o_simulador(self, api, cadastros):
        """O regime precisa acompanhar: é ele que classifica a renda."""
        _, fonte, _ = cadastros
        ano, mes = _competencia_atual()

        api.patch(
            reverse("fonte-renda-detail", args=[fonte["id"]]),
            {"regime": "pj"},
            format="json",
        )

        resumo = api.get(reverse("lancamento-resumo"), {"ano": ano, "mes": mes}).data
        regimes = {linha["regime"] for linha in resumo["por_regime"]}
        assert regimes == {"pj"}

    def test_nao_reescreve_o_passado(self, api, cadastros):
        household, fonte, _ = cadastros
        ano_anterior, mes_anterior = _mes_anterior()
        abrir_competencia(household, ano_anterior, mes_anterior)

        api.patch(
            reverse("fonte-renda-detail", args=[fonte["id"]]),
            {"valor_medio_mensal": "21000"},
            format="json",
        )

        passado = CashFlowEntry.objects.get(
            ano=ano_anterior, mes=mes_anterior, tipo="receita"
        )
        assert passado.valor_realizado == D("18000.00")

    def test_respeita_ajuste_manual_do_mes(self, api, cadastros):
        """Quem corrigiu o mês sabe de algo que o cadastro não sabe."""
        _, fonte, _ = cadastros
        ano, mes = _competencia_atual()

        lancamento = CashFlowEntry.objects.get(ano=ano, mes=mes, tipo="receita")
        api.patch(
            reverse("lancamento-detail", args=[lancamento.id]),
            {"valor_realizado": "19500"},
            format="json",
        )

        api.patch(
            reverse("fonte-renda-detail", args=[fonte["id"]]),
            {"valor_medio_mensal": "21000"},
            format="json",
        )

        lancamento.refresh_from_db()
        assert lancamento.valor_realizado == D("19500.00")


class TestDespesaFixa:
    def test_novo_valor_chega_ao_mes_corrente(self, api, cadastros):
        _, _, despesa = cadastros
        ano, mes = _competencia_atual()

        api.patch(
            reverse("despesa-fixa-detail", args=[despesa["id"]]),
            {"valor_previsto": "8600"},
            format="json",
        )

        resumo = api.get(reverse("lancamento-resumo"), {"ano": ano, "mes": mes}).data
        assert D(resumo["despesas_realizadas"]) == D("8600.00")

    def test_mudanca_de_categoria_acompanha(self, api, cadastros):
        _, _, despesa = cadastros
        ano, mes = _competencia_atual()

        api.patch(
            reverse("despesa-fixa-detail", args=[despesa["id"]]),
            {"categoria": "divida"},
            format="json",
        )

        lancamento = CashFlowEntry.objects.get(ano=ano, mes=mes, tipo="despesa")
        assert lancamento.categoria == "divida"

    def test_excluir_limpa_o_mes_aberto_e_preserva_o_passado(self, api, cadastros):
        household, _, despesa = cadastros
        ano, mes = _competencia_atual()
        ano_anterior, mes_anterior = _mes_anterior()
        abrir_competencia(household, ano_anterior, mes_anterior)

        api.delete(reverse("despesa-fixa-detail", args=[despesa["id"]]))

        assert not CashFlowEntry.objects.filter(ano=ano, mes=mes, tipo="despesa").exists()
        assert CashFlowEntry.objects.filter(
            ano=ano_anterior, mes=mes_anterior, tipo="despesa"
        ).exists()


class TestDependentesDaAlteracao:
    def test_dashboard_reflete_o_novo_valor(self, api, cadastros):
        """O painel lê lançamentos, então acompanha sem nenhum passo extra."""
        _, fonte, _ = cadastros

        api.patch(
            reverse("fonte-renda-detail", args=[fonte["id"]]),
            {"valor_medio_mensal": "21000"},
            format="json",
        )

        dashboard = api.get(reverse("dashboard")).data
        assert D(dashboard["fluxo_caixa"]["receitas_realizadas"]) == D("21000.00")

    def test_base_do_simulador_reflete_o_novo_valor(self, api, cadastros):
        _, fonte, _ = cadastros
        ano, mes = _competencia_atual()

        api.patch(
            reverse("fonte-renda-detail", args=[fonte["id"]]),
            {"valor_medio_mensal": "21000"},
            format="json",
        )

        base = api.get(reverse("simulador-base-real"), {"ano": ano, "mes": mes}).data
        assert D(base["total_familia"]) == D("21000.00")
