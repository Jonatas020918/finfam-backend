"""Abertura de competência: itens fixos virando lançamentos do mês.

É o mecanismo que garante uma única fonte de verdade — o fluxo de caixa lê só
`CashFlowEntry`, e o que é fixo chega lá por materialização.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.cashflow.competencia import abrir_competencia, competencias_com_movimento
from apps.cashflow.models import CashFlowEntry, RecurringExpense

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def familia_com_fixos(api, familia_autenticada):
    """Salário fixo + plantão variável + aluguel recorrente."""
    household, titular, _ = familia_autenticada

    api.post(
        reverse("fonte-renda-list"),
        {
            "membro": str(titular.id),
            "descricao": "Salário do hospital",
            "tipo": "clt_hospitalar",
            "regime": "clt",
            "valor_medio_mensal": "18000",
            "modo_lancamento": "fixa",
        },
        format="json",
    )
    api.post(
        reverse("fonte-renda-list"),
        {
            "membro": str(titular.id),
            "descricao": "Plantões",
            "tipo": "plantao",
            "regime": "pj",
            "valor_medio_mensal": "20000",
            "modo_lancamento": "variavel",
        },
        format="json",
    )
    api.post(
        reverse("despesa-fixa-list"),
        {
            "descricao": "Aluguel",
            "categoria": "despesa_fixa",
            "valor_previsto": "8000",
            "dia_vencimento": 10,
            "vigencia_inicio": "2026-01-01",
        },
        format="json",
    )
    return household, titular


class TestMaterializacao:
    def test_cria_lancamento_para_cada_item_fixo(self, api, familia_com_fixos):
        household, _ = familia_com_fixos

        resultado = abrir_competencia(household, 2026, 8)

        assert resultado.receitas_criadas == 1  # só o salário; plantão é variável
        assert resultado.despesas_criadas == 1
        assert CashFlowEntry.objects.filter(ano=2026, mes=8).count() == 2

    def test_receita_fixa_carrega_regime_e_membro(self, api, familia_com_fixos):
        household, titular = familia_com_fixos
        abrir_competencia(household, 2026, 8)

        receita = CashFlowEntry.objects.get(ano=2026, mes=8, tipo="receita")
        assert receita.regime == "clt"
        assert receita.tipo_renda == "clt_hospitalar"
        assert receita.membro_id == titular.id
        assert receita.valor_realizado == D("18000.00")

    def test_renda_variavel_nao_e_materializada(self, api, familia_com_fixos):
        household, _ = familia_com_fixos
        abrir_competencia(household, 2026, 8)

        descricoes = set(
            CashFlowEntry.objects.filter(ano=2026, mes=8).values_list("descricao", flat=True)
        )
        assert "Plantões" not in descricoes

    def test_abrir_de_novo_nao_duplica(self, api, familia_com_fixos):
        household, _ = familia_com_fixos
        abrir_competencia(household, 2026, 8)
        segunda = abrir_competencia(household, 2026, 8)

        assert segunda.criados == 0
        assert segunda.ja_existiam == 2
        assert CashFlowEntry.objects.filter(ano=2026, mes=8).count() == 2

    def test_ajuste_do_usuario_vence_a_recorrencia(self, api, familia_com_fixos):
        """Conta de luz de R$ 300 que veio R$ 800 não pode voltar para 300."""
        household, _ = familia_com_fixos
        abrir_competencia(household, 2026, 8)

        despesa = CashFlowEntry.objects.get(ano=2026, mes=8, tipo="despesa")
        despesa.valor_realizado = D("8500")
        despesa.save()

        abrir_competencia(household, 2026, 8)

        despesa.refresh_from_db()
        assert despesa.valor_realizado == D("8500.00")

    def test_meses_diferentes_recebem_lancamentos_proprios(self, api, familia_com_fixos):
        household, _ = familia_com_fixos
        abrir_competencia(household, 2026, 7)
        abrir_competencia(household, 2026, 8)

        assert CashFlowEntry.objects.filter(ano=2026, mes=7).count() == 2
        assert CashFlowEntry.objects.filter(ano=2026, mes=8).count() == 2


class TestVigencia:
    def _recorrente(self, household, **campos):
        padrao = {
            "tenant": household.tenant,
            "household": household,
            "descricao": "Parcela do carro",
            "categoria": "divida",
            "valor_previsto": D("2100"),
            "vigencia_inicio": date(2026, 3, 1),
        }
        return RecurringExpense.objects.create(**{**padrao, **campos})

    def test_nao_materializa_antes_do_inicio(self, familia_autenticada):
        household, _, _ = familia_autenticada
        self._recorrente(household)

        abrir_competencia(household, 2026, 2)
        assert CashFlowEntry.objects.filter(ano=2026, mes=2).count() == 0

    def test_para_de_materializar_depois_do_fim(self, familia_autenticada):
        """Financiamento quitado não pode inflar a despesa para sempre."""
        household, _, _ = familia_autenticada
        self._recorrente(household, vigencia_fim=date(2026, 6, 30))

        abrir_competencia(household, 2026, 6)
        abrir_competencia(household, 2026, 7)

        assert CashFlowEntry.objects.filter(ano=2026, mes=6).count() == 1
        assert CashFlowEntry.objects.filter(ano=2026, mes=7).count() == 0

    def test_recorrencia_inativa_e_ignorada(self, familia_autenticada):
        household, _, _ = familia_autenticada
        self._recorrente(household, ativa=False)

        abrir_competencia(household, 2026, 8)
        assert CashFlowEntry.objects.filter(ano=2026, mes=8).count() == 0


class TestApi:
    def test_abrir_competencia_via_api(self, api, familia_com_fixos):
        resposta = api.post(
            reverse("abrir-competencia"), {"ano": 2026, "mes": 8}, format="json"
        )

        assert resposta.status_code == 200
        assert resposta.data["criados"] == 2
        assert resposta.data["receitas_criadas"] == 1
        assert resposta.data["despesas_criadas"] == 1

    def test_lancamentos_marcam_o_que_e_recorrente(self, api, familia_com_fixos):
        api.post(reverse("abrir-competencia"), {"ano": 2026, "mes": 8}, format="json")

        lancamentos = api.get(reverse("lancamento-list"), {"ano": 2026, "mes": 8}).data["results"]
        assert all(item["recorrente"] for item in lancamentos)

    def test_resumo_ja_reflete_os_fixos(self, api, familia_com_fixos):
        """O ponto da mudança: o fluxo de caixa só lê lançamentos."""
        api.post(reverse("abrir-competencia"), {"ano": 2026, "mes": 8}, format="json")

        resumo = api.get(reverse("lancamento-resumo"), {"ano": 2026, "mes": 8}).data
        assert D(resumo["receitas_realizadas"]) == D("18000.00")
        assert D(resumo["despesas_realizadas"]) == D("8000.00")
        assert D(resumo["saldo_realizado"]) == D("10000.00")

    def test_mes_invalido_e_recusado(self, api, familia_autenticada):
        resposta = api.post(
            reverse("abrir-competencia"), {"ano": 2026, "mes": 13}, format="json"
        )
        assert resposta.status_code == 400

    def test_competencias_lista_meses_com_movimento(self, api, familia_com_fixos):
        api.post(reverse("abrir-competencia"), {"ano": 2026, "mes": 7}, format="json")
        api.post(reverse("abrir-competencia"), {"ano": 2026, "mes": 8}, format="json")

        competencias = api.get(reverse("competencias")).data["competencias"]
        assert {"ano": 2026, "mes": 8} in competencias
        assert {"ano": 2026, "mes": 7} in competencias

    def test_mes_corrente_sempre_aparece(self, api, familia_autenticada):
        hoje = date.today()
        competencias = api.get(reverse("competencias")).data["competencias"]
        assert competencias[0] == {"ano": hoje.year, "mes": hoje.month}


class TestDespesasFixasApi:
    def test_crud_de_despesa_fixa(self, api, familia_autenticada):
        criada = api.post(
            reverse("despesa-fixa-list"),
            {
                "descricao": "Escola",
                "categoria": "despesa_fixa",
                "valor_previsto": "3200",
                "vigencia_inicio": "2026-02-01",
            },
            format="json",
        )
        assert criada.status_code == 201

        atualizada = api.patch(
            reverse("despesa-fixa-detail", args=[criada.data["id"]]),
            {"valor_previsto": "3500"},
            format="json",
        )
        assert D(atualizada.data["valor_previsto"]) == D("3500.00")

        assert api.delete(
            reverse("despesa-fixa-detail", args=[criada.data["id"]])
        ).status_code == 204

    def test_recusa_fim_de_vigencia_antes_do_inicio(self, api, familia_autenticada):
        resposta = api.post(
            reverse("despesa-fixa-list"),
            {
                "descricao": "Erro",
                "valor_previsto": "100",
                "vigencia_inicio": "2026-08-01",
                "vigencia_fim": "2026-07-01",
            },
            format="json",
        )
        assert resposta.status_code == 400
        assert "vigencia_fim" in resposta.data

    def test_isolamento_entre_nucleos(self, api, familia, familia_autenticada):
        outra_household, _, _ = familia(
            email="outro@exemplo.com", nome="Outro", nome_familia="Família B"
        )
        RecurringExpense.objects.create(
            tenant=outra_household.tenant,
            household=outra_household,
            descricao="Despesa alheia",
            valor_previsto=D("999"),
            vigencia_inicio=date(2026, 1, 1),
        )

        listadas = api.get(reverse("despesa-fixa-list")).data["results"]
        assert listadas == []

    def test_competencias_nao_vazam_entre_nucleos(self, api, familia, familia_autenticada):
        outra_household, outro_titular, _ = familia(
            email="outro@exemplo.com", nome="Outro", nome_familia="Família B"
        )
        CashFlowEntry.objects.create(
            tenant=outra_household.tenant,
            household=outra_household,
            membro=outro_titular,
            tipo="receita",
            categoria="renda_trabalho",
            descricao="Alheio",
            valor_realizado=D("1000"),
            ano=2020,
            mes=5,
        )

        competencias = api.get(reverse("competencias")).data["competencias"]
        assert {"ano": 2020, "mes": 5} not in competencias
