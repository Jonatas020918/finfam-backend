"""As verificações que travam um deploy mal configurado.

O valor delas está justamente no cenário em que ninguém percebe nada: sem SMTP,
o e-mail de redefinição some no log e a API responde 200 do mesmo jeito. Por
isso o teste checa que a falha aparece — e que ela não atrapalha em DEBUG.
"""

import pytest

from apps.common.checks import (
    CONSOLE,
    cobranca_precisa_de_gateway_real,
    email_precisa_sair_da_maquina,
    hosts_precisam_ser_explicitos,
)


def ids(resultados):
    return [item.id for item in resultados]


class TestEmail:
    def test_console_em_producao_e_erro(self, settings):
        settings.DEBUG = False
        settings.EMAIL_BACKEND = CONSOLE
        assert ids(email_precisa_sair_da_maquina(None)) == ["finfam.E001"]

    def test_smtp_configurado_passa(self, settings):
        settings.DEBUG = False
        settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
        assert email_precisa_sair_da_maquina(None) == []

    def test_em_desenvolvimento_nao_atrapalha(self, settings):
        settings.DEBUG = True
        settings.EMAIL_BACKEND = CONSOLE
        assert email_precisa_sair_da_maquina(None) == []


class TestHosts:
    @pytest.mark.parametrize("hosts", [["*"], ["app.pulso.com.br", "*"]])
    def test_curinga_em_producao_e_erro(self, settings, hosts):
        settings.DEBUG = False
        settings.ALLOWED_HOSTS = hosts
        assert ids(hosts_precisam_ser_explicitos(None)) == ["finfam.E002"]

    def test_dominio_explicito_passa(self, settings):
        settings.DEBUG = False
        settings.ALLOWED_HOSTS = ["app.pulso.com.br"]
        assert hosts_precisam_ser_explicitos(None) == []


class TestGateway:
    def test_mock_em_producao_avisa(self, settings):
        settings.DEBUG = False
        settings.ASSINATURA_GATEWAY = "apps.billing.gateways_stripe.GatewayStripeMock"
        assert ids(cobranca_precisa_de_gateway_real(None)) == ["finfam.W001"]

    def test_gateway_real_passa(self, settings):
        settings.DEBUG = False
        settings.ASSINATURA_GATEWAY = "apps.billing.gateways_stripe.GatewayStripe"
        assert cobranca_precisa_de_gateway_real(None) == []
