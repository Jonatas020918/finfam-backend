"""Login com Google — token verificado, conta criada ou ligada por e-mail.

`verify_oauth2_token` fala com o Google pela rede; nestes testes ele é
substituído por um duplo que devolve claims prontas, do mesmo jeito que os
testes do Stripe substituem a chamada real por um mock (`test_stripe.py`).
"""

from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.billing.gateways import assinatura_do_household
from apps.billing.models import StatusAssinatura
from apps.households.models import Household, TipoMembro

pytestmark = pytest.mark.django_db


def claims(**extra):
    base = {
        "email": "dra.ana@exemplo.com",
        "email_verified": True,
        "sub": "10987654321",
        "name": "Ana Souza",
    }
    return {**base, **extra}


class TestContaNova:
    @patch("apps.accounts.views.google_id_token.verify_oauth2_token")
    def test_cria_usuario_household_e_titular_de_uma_vez(self, verificar, api):
        verificar.return_value = claims()

        resposta = api.post(reverse("google-login"), {"credential": "tok"}, format="json")

        assert resposta.status_code == 201
        assert resposta.data["criado"] is True
        assert resposta.data["access"]

        user = User.objects.get(email="dra.ana@exemplo.com")
        assert user.google_sub == "10987654321"
        assert user.has_usable_password() is False
        assert user.membro.tipo == TipoMembro.TITULAR
        assert Household.objects.filter(pk=user.membro.household_id).exists()

    @patch("apps.accounts.views.google_id_token.verify_oauth2_token")
    def test_conta_nova_nasce_com_assinatura_em_teste(self, verificar, api):
        verificar.return_value = claims()
        api.post(reverse("google-login"), {"credential": "tok"}, format="json")

        user = User.objects.get(email="dra.ana@exemplo.com")
        assinatura = assinatura_do_household(user.membro.household)
        assert assinatura.status == StatusAssinatura.TRIAL

    @patch("apps.accounts.views.google_id_token.verify_oauth2_token")
    def test_conta_nova_nao_nasce_com_termos_aceitos(self, verificar, api):
        """Entrar com o Google não é a mesma coisa que aceitar os termos —
        os dois precisam de ações separadas."""
        verificar.return_value = claims()
        resposta = api.post(reverse("google-login"), {"credential": "tok"}, format="json")

        assert resposta.data["user"]["termos_aceitos"] is False

    @patch("apps.accounts.views.google_id_token.verify_oauth2_token")
    def test_recusa_email_nao_verificado(self, verificar, api):
        verificar.return_value = claims(email_verified=False)

        resposta = api.post(reverse("google-login"), {"credential": "tok"}, format="json")

        assert resposta.status_code == 400
        assert not User.objects.filter(email="dra.ana@exemplo.com").exists()

    @patch("apps.accounts.views.google_id_token.verify_oauth2_token")
    def test_token_invalido_e_recusado(self, verificar, api):
        verificar.side_effect = ValueError("assinatura inválida")

        resposta = api.post(reverse("google-login"), {"credential": "tok"}, format="json")

        assert resposta.status_code == 400
        assert "credential" in resposta.data

    def test_exige_o_credential(self, api):
        resposta = api.post(reverse("google-login"), {}, format="json")
        assert resposta.status_code == 400


class TestContaExistente:
    @patch("apps.accounts.views.google_id_token.verify_oauth2_token")
    def test_liga_o_google_a_conta_ja_cadastrada_por_senha(self, verificar, api, familia):
        household, titular, user = familia(email="dra.ana@exemplo.com")
        assert user.google_sub is None
        verificar.return_value = claims()

        resposta = api.post(reverse("google-login"), {"credential": "tok"}, format="json")

        assert resposta.status_code == 200
        assert resposta.data["criado"] is False
        # Nenhum household segundo nasce: é a mesma conta, só ganhou um jeito
        # novo de entrar.
        assert Household.objects.count() == 1

        user.refresh_from_db()
        assert user.google_sub == "10987654321"

    @patch("apps.accounts.views.google_id_token.verify_oauth2_token")
    def test_entrar_de_novo_nao_duplica_nem_falha(self, verificar, api, familia):
        familia(email="dra.ana@exemplo.com")
        verificar.return_value = claims()

        api.post(reverse("google-login"), {"credential": "tok"}, format="json")
        segunda = api.post(reverse("google-login"), {"credential": "tok"}, format="json")

        assert segunda.status_code == 200
        assert User.objects.filter(email="dra.ana@exemplo.com").count() == 1

    @patch("apps.accounts.views.google_id_token.verify_oauth2_token")
    def test_email_e_normalizado_na_busca(self, verificar, api, familia):
        familia(email="dra.ana@exemplo.com")
        verificar.return_value = claims(email="Dra.Ana@Exemplo.com")

        resposta = api.post(reverse("google-login"), {"credential": "tok"}, format="json")

        assert resposta.status_code == 200
        assert resposta.data["criado"] is False
