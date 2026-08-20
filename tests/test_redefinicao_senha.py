"""Redefinição de senha por e-mail.

O caminho que mais importa aqui não é o feliz: é o de quem tenta usar o
formulário para descobrir quais médicos são clientes, e o de quem tenta reusar
um link antigo.
"""

import re

import pytest
from django.core import mail
from django.urls import reverse

pytestmark = pytest.mark.django_db

SENHA_ORIGINAL = "senha-muito-segura-123"
SENHA_NOVA = "outra-senha-bem-segura-456"


def _link_do_email():
    corpo = mail.outbox[-1].body
    return re.search(r"uid=([^&\s]+)&token=([^\s]+)", corpo).groups()


@pytest.fixture(autouse=True)
def contador_de_throttle_limpo():
    """O contador do throttle vive no cache e vazaria de um teste para o outro."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


class TestSolicitacao:
    def test_envia_email_com_link_para_o_frontend(self, api, familia, settings):
        settings.FRONTEND_URL = "https://app.batimento.com.br"
        familia(email="ana@exemplo.com")

        resposta = api.post(
            reverse("esqueci-senha"), {"email": "ana@exemplo.com"}, format="json"
        )

        assert resposta.status_code == 200
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["ana@exemplo.com"]
        assert "https://app.batimento.com.br/nova-senha?uid=" in mail.outbox[0].body

    def test_nao_revela_se_a_conta_existe(self, api, familia):
        """Resposta idêntica nos dois casos: o endpoint não é uma lista de clientes."""
        familia(email="ana@exemplo.com")

        existente = api.post(
            reverse("esqueci-senha"), {"email": "ana@exemplo.com"}, format="json"
        )
        inexistente = api.post(
            reverse("esqueci-senha"), {"email": "ninguem@exemplo.com"}, format="json"
        )

        assert existente.status_code == inexistente.status_code == 200
        assert existente.data == inexistente.data
        # Só a conta real recebe mensagem.
        assert len(mail.outbox) == 1

    def test_email_invalido_e_recusado(self, api):
        resposta = api.post(reverse("esqueci-senha"), {"email": "nao-e-email"}, format="json")
        assert resposta.status_code == 400
        assert mail.outbox == []

    def test_falha_de_envio_nao_vaza_a_existencia_da_conta(self, api, familia, monkeypatch):
        familia(email="ana@exemplo.com")
        monkeypatch.setattr(
            "apps.accounts.senha.send_mail",
            lambda **kwargs: (_ for _ in ()).throw(OSError("SMTP fora do ar")),
        )

        resposta = api.post(
            reverse("esqueci-senha"), {"email": "ana@exemplo.com"}, format="json"
        )
        assert resposta.status_code == 200

    def test_conta_inativa_nao_recebe_link(self, api, familia):
        _, _, user = familia(email="ana@exemplo.com")
        user.is_active = False
        user.save()

        api.post(reverse("esqueci-senha"), {"email": "ana@exemplo.com"}, format="json")
        assert mail.outbox == []


class TestConfirmacao:
    def _pedir_link(self, api, familia, email="ana@exemplo.com"):
        familia(email=email)
        api.post(reverse("esqueci-senha"), {"email": email}, format="json")
        return _link_do_email()

    def test_troca_a_senha_e_permite_entrar(self, api, familia):
        uid, token = self._pedir_link(api, familia)

        resposta = api.post(
            reverse("nova-senha"),
            {"uid": uid, "token": token, "password": SENHA_NOVA},
            format="json",
        )
        assert resposta.status_code == 200

        antiga = api.post(
            reverse("login"),
            {"email": "ana@exemplo.com", "password": SENHA_ORIGINAL},
            format="json",
        )
        nova = api.post(
            reverse("login"),
            {"email": "ana@exemplo.com", "password": SENHA_NOVA},
            format="json",
        )
        assert antiga.status_code == 401
        assert nova.status_code == 200

    def test_link_so_funciona_uma_vez(self, api, familia):
        """O token deriva do hash da senha: trocar a senha o invalida sozinho."""
        uid, token = self._pedir_link(api, familia)
        api.post(
            reverse("nova-senha"),
            {"uid": uid, "token": token, "password": SENHA_NOVA},
            format="json",
        )

        segunda = api.post(
            reverse("nova-senha"),
            {"uid": uid, "token": token, "password": "mais-uma-senha-segura-789"},
            format="json",
        )
        assert segunda.status_code == 400
        assert "expirou" in segunda.data["detail"]

    def test_token_de_outro_usuario_nao_serve(self, api, familia):
        uid, _ = self._pedir_link(api, familia, email="ana@exemplo.com")
        familia(email="bruno@exemplo.com", nome="Bruno", nome_familia="Família B")
        api.post(reverse("esqueci-senha"), {"email": "bruno@exemplo.com"}, format="json")
        _, token_do_bruno = _link_do_email()

        resposta = api.post(
            reverse("nova-senha"),
            {"uid": uid, "token": token_do_bruno, "password": SENHA_NOVA},
            format="json",
        )
        assert resposta.status_code == 400

    def test_link_expirado_e_recusado(self, api, familia, settings):
        uid, token = self._pedir_link(api, familia)
        # Prazo negativo: qualquer token, mesmo o recém-criado, já venceu.
        settings.PASSWORD_RESET_TIMEOUT = -1

        resposta = api.post(
            reverse("nova-senha"),
            {"uid": uid, "token": token, "password": SENHA_NOVA},
            format="json",
        )
        assert resposta.status_code == 400

    @pytest.mark.parametrize("uid", ["lixo", "", "!!!", "MTIz"])
    def test_uid_corrompido_responde_400_e_nao_500(self, api, familia, uid):
        _, token = self._pedir_link(api, familia)
        resposta = api.post(
            reverse("nova-senha"),
            {"uid": uid, "token": token, "password": SENHA_NOVA},
            format="json",
        )
        assert resposta.status_code == 400

    def test_senha_fraca_e_recusada(self, api, familia):
        uid, token = self._pedir_link(api, familia)
        resposta = api.post(
            reverse("nova-senha"),
            {"uid": uid, "token": token, "password": "123456"},
            format="json",
        )
        assert resposta.status_code == 400
        assert "password" in resposta.data


class TestLimiteDeTentativas:
    def test_solicitacao_para_no_limite_configurado(self, api, familia):
        """Sem limite, o formulário vira ferramenta de spam contra terceiros.

        Usa a taxa real do settings (5/hora), e não uma inventada no teste: é
        ela que vai valer em produção.
        """
        familia(email="ana@exemplo.com")

        codigos = [
            api.post(
                reverse("esqueci-senha"), {"email": "ana@exemplo.com"}, format="json"
            ).status_code
            for _ in range(6)
        ]

        assert codigos[:5] == [200] * 5
        assert codigos[5] == 429
        assert len(mail.outbox) == 5  # a sexta nem chega a enviar
