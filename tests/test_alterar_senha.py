"""Troca de senha por quem já está logado (tela de perfil).

Duas contas nascem de jeitos diferentes e o comportamento precisa refletir
isso: quem tem senha (cadastro tradicional) precisa confirmar a atual antes
de trocar; quem entrou só pelo Google nunca teve uma, então não há o que
confirmar — só definir a primeira.
"""

import pytest
from django.urls import reverse

from apps.accounts.models import User

pytestmark = pytest.mark.django_db

SENHA = "senha-muito-segura-123"
SENHA_NOVA = "outra-senha-bem-forte-456"


class TestAlterarSenha:
    def test_exige_autenticacao(self, api):
        resposta = api.post(
            reverse("alterar-senha"),
            {"senha_atual": SENHA, "nova_senha": SENHA_NOVA},
            format="json",
        )
        assert resposta.status_code == 401

    def test_exige_a_senha_atual_correta(self, api, familia_autenticada):
        _, _, usuario = familia_autenticada

        resposta = api.post(
            reverse("alterar-senha"),
            {"senha_atual": "chute-errado", "nova_senha": SENHA_NOVA},
            format="json",
        )

        assert resposta.status_code == 400
        # Lista, e não string solta: a tela mostra o primeiro item do campo, e
        # uma string faria aparecer só a letra "S" no lugar do recado inteiro.
        assert resposta.data["senha_atual"] == ["Senha atual incorreta."]
        usuario.refresh_from_db()
        assert usuario.check_password(SENHA)

    def test_troca_a_senha_com_a_atual_correta(self, api, familia_autenticada):
        _, _, usuario = familia_autenticada

        resposta = api.post(
            reverse("alterar-senha"),
            {"senha_atual": SENHA, "nova_senha": SENHA_NOVA},
            format="json",
        )

        assert resposta.status_code == 200
        usuario.refresh_from_db()
        assert usuario.check_password(SENHA_NOVA)
        assert not usuario.check_password(SENHA)

    def test_recusa_senha_nova_fraca(self, api, familia_autenticada):
        resposta = api.post(
            reverse("alterar-senha"),
            {"senha_atual": SENHA, "nova_senha": "123"},
            format="json",
        )

        assert resposta.status_code == 400
        assert "nova_senha" in resposta.data

    def test_conta_so_com_google_define_senha_sem_informar_a_atual(
        self, api, tenant_plataforma
    ):
        usuario = User.objects.create_user(
            email="google@exemplo.com",
            password=None,
            nome_completo="Conta Google",
            tenant=tenant_plataforma,
            google_sub="10987654321",
        )
        assert usuario.has_usable_password() is False
        api.force_authenticate(user=usuario)

        resposta = api.post(
            reverse("alterar-senha"),
            {"nova_senha": SENHA_NOVA},
            format="json",
        )

        assert resposta.status_code == 200
        usuario.refresh_from_db()
        assert usuario.check_password(SENHA_NOVA)

    def test_o_perfil_informa_se_a_conta_tem_senha(self, api, familia_autenticada):
        resposta = api.get(reverse("me"))
        assert resposta.data["possui_senha"] is True

    def test_o_perfil_de_conta_so_google_informa_que_nao_tem_senha(
        self, api, tenant_plataforma
    ):
        usuario = User.objects.create_user(
            email="google2@exemplo.com",
            password=None,
            nome_completo="Conta Google",
            tenant=tenant_plataforma,
            google_sub="123456789",
        )
        api.force_authenticate(user=usuario)

        resposta = api.get(reverse("me"))
        assert resposta.data["possui_senha"] is False
