"""Isolamento entre núcleos familiares (seção 2.4).

É o teste mais importante do produto do ponto de vista de risco: um vazamento
aqui expõe dados financeiros de um cliente a outro.
"""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def duas_familias(api, familia):
    familia_a = familia(email="ana@exemplo.com", nome="Ana", nome_familia="Família A")
    familia_b = familia(email="bruno@exemplo.com", nome="Bruno", nome_familia="Família B")
    return familia_a, familia_b


def _criar_lancamento(household, membro, descricao):
    from apps.cashflow.models import CashFlowEntry

    return CashFlowEntry.objects.create(
        tenant=household.tenant,
        household=household,
        membro=membro,
        tipo="receita",
        categoria="renda_trabalho",
        descricao=descricao,
        valor_realizado="10000",
        ano=2026,
        mes=8,
    )


class TestIsolamentoDeLeitura:
    def test_listagem_so_traz_dados_do_proprio_nucleo(self, api, duas_familias):
        (hh_a, membro_a, user_a), (hh_b, membro_b, _) = duas_familias
        _criar_lancamento(hh_a, membro_a, "Plantão da Ana")
        _criar_lancamento(hh_b, membro_b, "Plantão do Bruno")

        api.force_authenticate(user=user_a)
        resposta = api.get(reverse("lancamento-list"))
        descricoes = [item["descricao"] for item in resposta.data["results"]]
        assert descricoes == ["Plantão da Ana"]

    def test_membros_de_outra_familia_nao_aparecem(self, api, duas_familias):
        (_, _, user_a), (_, membro_b, _) = duas_familias
        api.force_authenticate(user=user_a)
        ids = [m["id"] for m in api.get(reverse("membro-list")).data["results"]]
        assert str(membro_b.id) not in ids

    def test_acesso_direto_por_id_alheio_retorna_404(self, api, duas_familias):
        (hh_a, membro_a, user_a), (hh_b, membro_b, _) = duas_familias
        lancamento_b = _criar_lancamento(hh_b, membro_b, "Plantão do Bruno")

        api.force_authenticate(user=user_a)
        resposta = api.get(reverse("lancamento-detail", args=[lancamento_b.id]))
        assert resposta.status_code == 404


class TestIsolamentoDeEscrita:
    def test_nao_edita_registro_de_outra_familia(self, api, duas_familias):
        (_, _, user_a), (hh_b, membro_b, _) = duas_familias
        lancamento_b = _criar_lancamento(hh_b, membro_b, "Plantão do Bruno")

        api.force_authenticate(user=user_a)
        resposta = api.patch(
            reverse("lancamento-detail", args=[lancamento_b.id]),
            {"valor_realizado": "1"},
            format="json",
        )
        assert resposta.status_code == 404
        lancamento_b.refresh_from_db()
        assert str(lancamento_b.valor_realizado) == "10000.00"

    def test_nao_vincula_lancamento_a_membro_de_outra_familia(self, api, duas_familias):
        (_, _, user_a), (_, membro_b, _) = duas_familias
        api.force_authenticate(user=user_a)
        resposta = api.post(
            reverse("lancamento-list"),
            {
                "membro": str(membro_b.id),
                "tipo": "despesa",
                "categoria": "despesa_fixa",
                "descricao": "Tentativa",
                "valor_realizado": "100",
                "ano": 2026,
                "mes": 8,
            },
            format="json",
        )
        assert resposta.status_code == 400

    def test_criacao_herda_household_e_tenant_do_usuario(self, api, familia_autenticada):
        household, _, _ = familia_autenticada
        resposta = api.post(
            reverse("meta-list"),
            {"descricao": "Reserva de emergência", "valor_alvo": "120000"},
            format="json",
        )
        assert resposta.status_code == 201

        from apps.goals.models import Goal

        meta = Goal.objects.get(pk=resposta.data["id"])
        assert meta.household_id == household.id
        assert meta.tenant_id == household.tenant_id

    def test_nao_e_possivel_forjar_household_no_payload(self, api, duas_familias):
        (_, _, user_a), (hh_b, _, _) = duas_familias
        api.force_authenticate(user=user_a)
        resposta = api.post(
            reverse("meta-list"),
            {"descricao": "Meta", "valor_alvo": "1000", "household": str(hh_b.id)},
            format="json",
        )
        assert resposta.status_code == 201

        from apps.goals.models import Goal

        meta = Goal.objects.get(pk=resposta.data["id"])
        assert meta.household_id != hh_b.id
