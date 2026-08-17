"""Lançamento mensal por fonte de renda e projeção de longo prazo."""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.simulators.projecao import Premissas, projetar

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def fonte_variavel(api, familia_autenticada):
    """Plantão: renda que muda todo mês — o caso que motiva o modo detalhado."""
    _, titular, _ = familia_autenticada
    return api.post(
        reverse("fonte-renda-list"),
        {
            "membro": str(titular.id),
            "descricao": "Plantões",
            "tipo": "plantao",
            "regime": "pj",
            "valor_medio_mensal": "20000",
            "modo_lancamento": "mensal",
        },
        format="json",
    ).data


class TestModoDeLancamento:
    def test_padrao_e_media(self, api, familia_autenticada):
        _, titular, _ = familia_autenticada
        fonte = api.post(
            reverse("fonte-renda-list"),
            {
                "membro": str(titular.id),
                "descricao": "Salário",
                "tipo": "clt_hospitalar",
                "regime": "clt",
                "valor_medio_mensal": "18000",
            },
            format="json",
        ).data
        assert fonte["modo_lancamento"] == "media"
        assert fonte["detalhada"] is False
        assert fonte["media_realizada"] is None

    def test_fonte_detalhada_expoe_media_realizada(self, api, fonte_variavel):
        url = reverse("fonte-renda-competencia", args=[fonte_variavel["id"]])
        api.post(url, {"ano": 2026, "mes": 6, "valor_realizado": "18000"}, format="json")
        api.post(url, {"ano": 2026, "mes": 7, "valor_realizado": "26000"}, format="json")

        fonte = api.get(reverse("fonte-renda-detail", args=[fonte_variavel["id"]])).data
        assert fonte["detalhada"] is True
        assert D(fonte["media_realizada"]) == D("22000.00")


class TestLancamentoPorCompetencia:
    def test_cria_receita_herdando_regime_e_membro(self, api, fonte_variavel, familia_autenticada):
        _, titular, _ = familia_autenticada
        resposta = api.post(
            reverse("fonte-renda-competencia", args=[fonte_variavel["id"]]),
            {"ano": 2026, "mes": 8, "valor_realizado": "31500"},
            format="json",
        )
        assert resposta.status_code == 201
        assert resposta.data["criado"] is True

        lancamentos = api.get(reverse("lancamento-list"), {"ano": 2026, "mes": 8}).data["results"]
        assert len(lancamentos) == 1
        assert lancamentos[0]["regime"] == "pj"
        assert lancamentos[0]["tipo_renda"] == "plantao"
        assert str(lancamentos[0]["membro"]) == str(titular.id)

    def test_relancar_o_mesmo_mes_corrige_em_vez_de_duplicar(self, api, fonte_variavel):
        url = reverse("fonte-renda-competencia", args=[fonte_variavel["id"]])
        api.post(url, {"ano": 2026, "mes": 8, "valor_realizado": "31500"}, format="json")
        resposta = api.post(url, {"ano": 2026, "mes": 8, "valor_realizado": "28000"}, format="json")

        assert resposta.status_code == 200
        assert resposta.data["criado"] is False

        resumo = api.get(reverse("lancamento-resumo"), {"ano": 2026, "mes": 8}).data
        assert D(resumo["receitas_realizadas"]) == D("28000.00")

    def test_historico_lista_as_competencias(self, api, fonte_variavel):
        url = reverse("fonte-renda-competencia", args=[fonte_variavel["id"]])
        for mes, valor in [(6, "18000"), (7, "26000"), (8, "22000")]:
            api.post(url, {"ano": 2026, "mes": mes, "valor_realizado": valor}, format="json")

        historico = api.get(reverse("fonte-renda-historico", args=[fonte_variavel["id"]])).data
        assert [c["mes"] for c in historico["competencias"]] == [8, 7, 6]
        assert D(historico["media_realizada"]) == D("22000.00")

    def test_mes_invalido_e_recusado(self, api, fonte_variavel):
        resposta = api.post(
            reverse("fonte-renda-competencia", args=[fonte_variavel["id"]]),
            {"ano": 2026, "mes": 13, "valor_realizado": "1000"},
            format="json",
        )
        assert resposta.status_code == 400

    def test_nao_lanca_em_fonte_de_outro_nucleo(self, api, familia, familia_autenticada):
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

        resposta = api.post(
            reverse("fonte-renda-competencia", args=[fonte_alheia.id]),
            {"ano": 2026, "mes": 8, "valor_realizado": "5000"},
            format="json",
        )
        assert resposta.status_code == 404


class TestMotorDeProjecao:
    def _premissas(self, **ajustes):
        base = dict(
            meses_base=12,
            anos=10,
            rentabilidade_real_anual=D("4"),
            crescimento_renda_anual=D("0"),
            inflacao_despesas_anual=D("0"),
        )
        base.update(ajustes)
        return Premissas(**base)

    def test_serie_cobre_o_horizonte_pedido(self):
        resultado = projetar(D("40000"), D("25000"), D("100000"), self._premissas(anos=5))
        assert len(resultado["serie"]) == 6  # ano 0 + 5 anos
        assert resultado["serie"][0]["patrimonio"] == D("100000.00")

    def test_patrimonio_cresce_com_aporte_e_rendimento(self):
        resultado = projetar(D("40000"), D("25000"), D("100000"), self._premissas(anos=10))
        final = resultado["resultado"]
        # 15 mil por mês durante 10 anos = 1,8 milhão aportado, mais rendimento.
        assert final["total_aportado"] == D("1800000.00")
        assert final["total_rendimento"] > 0
        assert final["patrimonio_final"] > D("1900000.00")

    def test_sem_rendimento_o_patrimonio_e_so_a_soma_dos_aportes(self):
        resultado = projetar(
            D("30000"), D("20000"), D("0"), self._premissas(anos=1, rentabilidade_real_anual=D("0"))
        )
        assert resultado["resultado"]["patrimonio_final"] == D("120000.00")
        assert resultado["resultado"]["total_rendimento"] == D("0.00")

    def test_aporte_manual_substitui_a_sobra_observada(self):
        resultado = projetar(
            D("40000"), D("25000"), D("0"),
            self._premissas(anos=1, rentabilidade_real_anual=D("0"), aporte_mensal_manual=D("5000")),
        )
        assert resultado["resultado"]["total_aportado"] == D("60000.00")

    def test_despesa_subindo_mais_que_renda_reduz_o_aporte(self):
        crescendo = projetar(
            D("40000"), D("25000"), D("0"),
            self._premissas(anos=5, crescimento_renda_anual=D("2"), inflacao_despesas_anual=D("8")),
        )
        estavel = projetar(D("40000"), D("25000"), D("0"), self._premissas(anos=5))
        assert crescendo["resultado"]["patrimonio_final"] < estavel["resultado"]["patrimonio_final"]

    def test_alerta_quando_nao_sobra_dinheiro(self):
        resultado = projetar(D("20000"), D("22000"), D("50000"), self._premissas(anos=5))
        assert any("despesas alcançaram" in a for a in resultado["alertas"])

    def test_alerta_de_base_curta_e_de_horizonte_longo(self):
        resultado = projetar(
            D("30000"), D("20000"), D("0"), self._premissas(meses_base=2, anos=15)
        )
        assert any("poucos meses" in a for a in resultado["alertas"])
        assert any("10 anos ou mais" in a for a in resultado["alertas"])

    def test_disclaimer_deixa_claro_que_nao_e_promessa(self):
        resultado = projetar(D("30000"), D("20000"), D("0"), self._premissas())
        assert "não garante" in resultado["disclaimer"]

    @pytest.mark.parametrize("meses,anos", [(0, 5), (25, 5), (12, 0), (12, 16)])
    def test_limites_dos_parametros(self, meses, anos):
        with pytest.raises(ValueError):
            Premissas(
                meses_base=meses,
                anos=anos,
                rentabilidade_real_anual=D("4"),
                crescimento_renda_anual=D("0"),
                inflacao_despesas_anual=D("0"),
            )


class TestProjecaoViaAPI:
    def _lancar(self, api, mes, receita, despesa, ano=2026):
        for tipo, categoria, valor in [
            ("receita", "renda_trabalho", receita),
            ("despesa", "despesa_fixa", despesa),
        ]:
            api.post(
                reverse("lancamento-list"),
                {
                    "tipo": tipo,
                    "categoria": categoria,
                    "descricao": "Movimento",
                    "valor_realizado": valor,
                    "ano": ano,
                    "mes": mes,
                },
                format="json",
            )

    def test_usa_o_historico_real_como_base(self, api, familia_autenticada):
        from datetime import date

        hoje = date.today()
        self._lancar(api, hoje.month, "40000", "25000", ano=hoje.year)

        dados = api.get(reverse("simulador-projecao"), {"meses_base": 1, "anos": 5}).data
        assert D(dados["base"]["receitas_medias_mensais"]) == D("40000.00")
        assert D(dados["base"]["sobra_media_mensal"]) == D("15000.00")
        assert dados["base"]["meses_considerados"] == 1
        assert len(dados["serie"]) == 6

    def test_premissas_voltam_na_resposta(self, api, familia_autenticada):
        dados = api.post(
            reverse("simulador-projecao"),
            {"meses_base": 6, "anos": 12, "rentabilidade_real_anual": "6.5"},
            format="json",
        ).data
        assert dados["premissas"]["anos_projetados"] == 12
        assert D(dados["premissas"]["rentabilidade_real_anual"]) == D("6.50")

    def test_recusa_horizonte_acima_do_limite(self, api, familia_autenticada):
        resposta = api.post(
            reverse("simulador-projecao"), {"anos": 20}, format="json"
        )
        assert resposta.status_code == 400
        assert "anos" in resposta.data

    def test_recusa_janela_de_base_acima_de_24_meses(self, api, familia_autenticada):
        resposta = api.post(
            reverse("simulador-projecao"), {"meses_base": 36}, format="json"
        )
        assert resposta.status_code == 400

    def test_exige_autenticacao(self, api):
        api.force_authenticate(user=None)
        assert api.get(reverse("simulador-projecao")).status_code == 401
