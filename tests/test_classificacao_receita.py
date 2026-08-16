"""Classificação tributária das receitas do fluxo de caixa.

É o elo que faz o simulador PJ x CLT trabalhar com o que a pessoa realmente
recebeu, em vez de um valor redigitado.
"""

from decimal import Decimal

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def familia_com_fontes(api, familia_autenticada):
    """Titular PJ + cônjuge CLT — o caso do casal de médicos da especificação."""
    household, titular, _ = familia_autenticada

    conjuge = api.post(
        reverse("membro-list"), {"tipo": "conjuge", "nome": "Bruno Souza"}, format="json"
    ).data

    fonte_pj = api.post(
        reverse("fonte-renda-list"),
        {
            "membro": str(titular.id),
            "descricao": "Consultório",
            "tipo": "pj_consultorio",
            "regime": "pj",
            "valor_medio_mensal": "40000",
        },
        format="json",
    ).data

    fonte_clt = api.post(
        reverse("fonte-renda-list"),
        {
            "membro": conjuge["id"],
            "descricao": "Hospital",
            "tipo": "clt_hospitalar",
            "regime": "clt",
            "valor_medio_mensal": "15000",
        },
        format="json",
    ).data

    return household, titular, conjuge, fonte_pj, fonte_clt


def _receita(api, **campos):
    payload = {
        "tipo": "receita",
        "categoria": "renda_trabalho",
        "ano": 2026,
        "mes": 8,
        **campos,
    }
    return api.post(reverse("lancamento-list"), payload, format="json")


class TestVinculoComFonteDeRenda:
    def test_lancamento_herda_regime_tipo_e_membro_da_fonte(self, api, familia_com_fontes):
        _, titular, _, fonte_pj, _ = familia_com_fontes

        resposta = _receita(
            api,
            fonte_renda=fonte_pj["id"],
            descricao="Faturamento de agosto",
            valor_realizado="42000",
        )

        assert resposta.status_code == 201, resposta.data
        assert resposta.data["regime"] == "pj"
        assert resposta.data["tipo_renda"] == "pj_consultorio"
        assert str(resposta.data["membro"]) == str(titular.id)
        assert resposta.data["regime_display"] == "PJ (Simples Nacional)"

    def test_regime_informado_a_mao_nao_sobrepoe_o_da_fonte(self, api, familia_com_fontes):
        """A fonte é a origem da verdade — senão os dois divergem com o tempo."""
        _, _, _, fonte_pj, _ = familia_com_fontes

        resposta = _receita(
            api,
            fonte_renda=fonte_pj["id"],
            regime="clt",
            descricao="Faturamento",
            valor_realizado="42000",
        )

        assert resposta.status_code == 201
        assert resposta.data["regime"] == "pj"

    def test_recusa_membro_divergente_da_fonte(self, api, familia_com_fontes):
        _, _, conjuge, fonte_pj, _ = familia_com_fontes

        resposta = _receita(
            api,
            fonte_renda=fonte_pj["id"],
            membro=conjuge["id"],
            descricao="Faturamento",
            valor_realizado="42000",
        )

        assert resposta.status_code == 400
        assert "membro" in resposta.data

    def test_recusa_fonte_de_outro_nucleo_familiar(self, api, familia, familia_autenticada):
        outra_household, outro_titular, _ = familia(
            email="outro@exemplo.com", nome="Outro", nome_familia="Família B"
        )
        from apps.households.models import IncomeSource

        fonte_alheia = IncomeSource.objects.create(
            tenant=outra_household.tenant,
            household=outra_household,
            membro=outro_titular,
            descricao="Fonte alheia",
            tipo="plantao",
            regime="pj",
            valor_medio_mensal=D("10000"),
        )

        resposta = _receita(
            api, fonte_renda=str(fonte_alheia.id), descricao="X", valor_realizado="1000"
        )
        assert resposta.status_code == 400

    def test_receita_avulsa_pode_declarar_o_regime_direto(self, api, familia_autenticada):
        """Nem toda receita tem fonte cadastrada — plantão eventual, por exemplo."""
        resposta = _receita(
            api,
            regime="autonomo",
            tipo_renda="plantao",
            descricao="Plantão avulso",
            valor_realizado="3500",
        )

        assert resposta.status_code == 201
        assert resposta.data["regime"] == "autonomo"

    def test_despesa_nao_aceita_classificacao_de_renda(self, api, familia_autenticada):
        resposta = api.post(
            reverse("lancamento-list"),
            {
                "tipo": "despesa",
                "categoria": "despesa_fixa",
                "descricao": "Aluguel",
                "valor_realizado": "8000",
                "regime": "pj",
                "ano": 2026,
                "mes": 8,
            },
            format="json",
        )
        assert resposta.status_code == 400


class TestResumoPorRegime:
    def test_resumo_separa_receitas_por_regime(self, api, familia_com_fontes):
        _, _, _, fonte_pj, fonte_clt = familia_com_fontes
        _receita(api, fonte_renda=fonte_pj["id"], descricao="Consultório", valor_realizado="40000")
        _receita(api, fonte_renda=fonte_clt["id"], descricao="Salário", valor_realizado="15000")
        _receita(api, regime="autonomo", descricao="Plantão avulso", valor_realizado="5000")

        resumo = api.get(reverse("lancamento-resumo"), {"ano": 2026, "mes": 8}).data
        por_regime = {linha["regime"]: linha for linha in resumo["por_regime"]}

        assert D(por_regime["pj"]["receitas"]) == D("40000.00")
        assert D(por_regime["clt"]["receitas"]) == D("15000.00")
        assert D(por_regime["autonomo"]["receitas"]) == D("5000.00")
        assert D(por_regime["pj"]["participacao_percentual"]) == D("66.67")

    def test_resumo_agrupa_por_fonte(self, api, familia_com_fontes):
        _, _, _, fonte_pj, _ = familia_com_fontes
        _receita(api, fonte_renda=fonte_pj["id"], descricao="1ª quinzena", valor_realizado="20000")
        _receita(api, fonte_renda=fonte_pj["id"], descricao="2ª quinzena", valor_realizado="22000")

        resumo = api.get(reverse("lancamento-resumo"), {"ano": 2026, "mes": 8}).data
        fontes = {linha["descricao"]: linha for linha in resumo["por_fonte"]}

        assert D(fontes["Consultório"]["receitas"]) == D("42000.00")
        assert fontes["Consultório"]["membro_nome"] == "Ana Souza"

    def test_receita_sem_regime_fica_destacada(self, api, familia_autenticada):
        _receita(api, descricao="Recebimento sem classificar", valor_realizado="7000")

        resumo = api.get(reverse("lancamento-resumo"), {"ano": 2026, "mes": 8}).data
        assert D(resumo["receitas_nao_classificadas"]) == D("7000.00")
        assert resumo["por_regime"] == []


class TestBaseRealParaSimulacao:
    def test_devolve_bruto_e_regime_predominante_por_membro(self, api, familia_com_fontes):
        _, titular, conjuge, fonte_pj, fonte_clt = familia_com_fontes
        _receita(api, fonte_renda=fonte_pj["id"], descricao="Consultório", valor_realizado="40000")
        _receita(api, fonte_renda=fonte_clt["id"], descricao="Salário", valor_realizado="15000")

        dados = api.get(reverse("simulador-base-real"), {"ano": 2026, "mes": 8}).data
        por_membro = {m["membro_nome"]: m for m in dados["por_membro"]}

        assert D(dados["total_familia"]) == D("55000.00")
        assert D(por_membro["Ana Souza"]["receita_bruta_mensal"]) == D("40000.00")
        assert por_membro["Ana Souza"]["regime_predominante"] == "pj"
        assert por_membro["Bruno Souza"]["regime_predominante"] == "clt"

    def test_regime_predominante_considera_o_maior_valor(self, api, familia_com_fontes):
        """Médico com plantão PJ e vínculo CLT: vale o que pesa mais no bolso."""
        _, titular, _, fonte_pj, _ = familia_com_fontes
        _receita(api, fonte_renda=fonte_pj["id"], descricao="Consultório", valor_realizado="12000")
        _receita(
            api,
            membro=str(titular.id),
            regime="clt",
            descricao="Hospital",
            valor_realizado="20000",
        )

        dados = api.get(reverse("simulador-base-real"), {"ano": 2026, "mes": 8}).data
        ana = next(m for m in dados["por_membro"] if m["membro_nome"] == "Ana Souza")

        assert D(ana["receita_bruta_mensal"]) == D("32000.00")
        assert ana["regime_predominante"] == "clt"
        assert D(ana["por_regime"]["pj"]) == D("12000.00")

    def test_mes_sem_lancamentos_devolve_estrutura_vazia(self, api, familia_autenticada):
        dados = api.get(reverse("simulador-base-real"), {"ano": 2026, "mes": 1}).data
        assert dados["por_membro"] == []
        assert D(dados["total_familia"]) == D("0.00")

    def test_exige_autenticacao(self, api):
        api.force_authenticate(user=None)
        assert api.get(reverse("simulador-base-real")).status_code == 401

    def test_nao_enxerga_lancamentos_de_outro_nucleo(self, api, familia, familia_autenticada):
        outra_household, outro_titular, _ = familia(
            email="outro@exemplo.com", nome="Outro", nome_familia="Família B"
        )
        from apps.cashflow.models import CashFlowEntry

        CashFlowEntry.objects.create(
            tenant=outra_household.tenant,
            household=outra_household,
            membro=outro_titular,
            tipo="receita",
            categoria="renda_trabalho",
            descricao="Renda alheia",
            valor_realizado=D("99000"),
            regime="pj",
            ano=2026,
            mes=8,
        )

        dados = api.get(reverse("simulador-base-real"), {"ano": 2026, "mes": 8}).data
        assert D(dados["total_familia"]) == D("0.00")
