"""Autenticação, cadastro self-service e onboarding."""

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.households.models import Household, TipoMembro

pytestmark = pytest.mark.django_db


class TestSignup:
    def test_cria_usuario_household_e_titular_de_uma_vez(self, api, tenant_plataforma):
        resposta = api.post(
            reverse("signup"),
            {
                "email": "Dra.Ana@Exemplo.com",
                "password": "senha-muito-segura-123",
                "nome_completo": "Ana Souza",
            },
            format="json",
        )
        assert resposta.status_code == 201
        assert resposta.data["access"]

        user = User.objects.get(email="dra.ana@exemplo.com")  # normalizado
        household = Household.objects.get()
        assert household.tenant_id == tenant_plataforma.id
        assert household.modo == "self_service"
        assert user.membro.tipo == TipoMembro.TITULAR
        assert user.membro.household_id == household.id

    def test_rejeita_email_duplicado(self, api, familia):
        familia(email="ana@exemplo.com")
        resposta = api.post(
            reverse("signup"),
            {
                "email": "ana@exemplo.com",
                "password": "senha-muito-segura-123",
                "nome_completo": "Outra Ana",
            },
            format="json",
        )
        assert resposta.status_code == 400
        assert "email" in resposta.data

    def test_rejeita_senha_fraca(self, api, tenant_plataforma):
        resposta = api.post(
            reverse("signup"),
            {"email": "b@exemplo.com", "password": "123456", "nome_completo": "B"},
            format="json",
        )
        assert resposta.status_code == 400
        assert "password" in resposta.data


class TestLogin:
    def test_login_devolve_tokens(self, api, familia):
        familia(email="ana@exemplo.com")
        resposta = api.post(
            reverse("login"),
            {"email": "ana@exemplo.com", "password": "senha-muito-segura-123"},
            format="json",
        )
        assert resposta.status_code == 200
        assert "access" in resposta.data and "refresh" in resposta.data

    def test_senha_errada_nao_autentica(self, api, familia):
        familia(email="ana@exemplo.com")
        resposta = api.post(
            reverse("login"),
            {"email": "ana@exemplo.com", "password": "errada"},
            format="json",
        )
        assert resposta.status_code == 401


class TestEndpointsProtegidos:
    @pytest.mark.parametrize(
        "rota", ["me", "meu-household", "dashboard", "membro-list", "lancamento-list"]
    )
    def test_exigem_autenticacao(self, api, rota):
        assert api.get(reverse(rota)).status_code == 401


class TestOnboarding:
    def test_fluxo_completo_do_onboarding(self, api, familia_autenticada):
        household, titular, _ = familia_autenticada

        # 1. estado civil e regime de bens
        resposta = api.patch(
            reverse("meu-household"),
            {"estado_civil": "casado", "regime_bens": "comunhao_parcial"},
            format="json",
        )
        assert resposta.status_code == 200

        # 2. cônjuge com renda própria
        conjuge = api.post(
            reverse("membro-list"),
            {"tipo": "conjuge", "nome": "Bruno Souza", "profissao": "Médico"},
            format="json",
        )
        assert conjuge.status_code == 201

        # 3. fontes de renda por membro (regimes diferentes)
        for membro_id, regime, valor in [
            (str(titular.id), "pj", "42000.00"),
            (conjuge.data["id"], "clt", "18000.00"),
        ]:
            r = api.post(
                reverse("fonte-renda-list"),
                {
                    "membro": membro_id,
                    "descricao": "Atendimento",
                    "tipo": "pj_consultorio",
                    "regime": regime,
                    "valor_medio_mensal": valor,
                },
                format="json",
            )
            assert r.status_code == 201, r.data

        # 4. patrimônio, dívida e objetivo
        assert api.post(
            reverse("patrimonio-list"),
            {"tipo": "imovel", "descricao": "Apartamento", "valor_atual": "1200000",
             "titularidade": "conjunto"},
            format="json",
        ).status_code == 201
        assert api.post(
            reverse("divida-list"),
            {"tipo": "financiamento_imovel", "descricao": "Financiamento",
             "saldo_devedor": "600000", "taxa_juros_mensal": "0.85",
             "parcelas_restantes": 240, "valor_parcela": "6200"},
            format="json",
        ).status_code == 201
        assert api.post(
            reverse("objetivo-list"),
            {"categoria": "aposentadoria", "descricao": "Aposentar aos 60",
             "horizonte_anos": 25},
            format="json",
        ).status_code == 201

        # 5. conclusão
        final = api.post(reverse("concluir-onboarding"))
        assert final.status_code == 200
        assert final.data["onboarding_concluido"] is True
        assert len(final.data["membros"]) == 2

    def test_nao_permite_segundo_titular(self, api, familia_autenticada):
        resposta = api.post(
            reverse("membro-list"), {"tipo": "titular", "nome": "Outro"}, format="json"
        )
        assert resposta.status_code == 400
        assert "titular" in str(resposta.data).lower()

    def test_dependente_nao_pode_ter_fonte_de_renda(self, api, familia_autenticada):
        dependente = api.post(
            reverse("membro-list"), {"tipo": "dependente", "nome": "Filho"}, format="json"
        )
        resposta = api.post(
            reverse("fonte-renda-list"),
            {
                "membro": dependente.data["id"],
                "descricao": "Mesada",
                "tipo": "outra",
                "regime": "clt",
                "valor_medio_mensal": "500",
            },
            format="json",
        )
        assert resposta.status_code == 400
