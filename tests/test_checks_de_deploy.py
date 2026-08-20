"""As verificações que travam um deploy mal configurado.

O valor delas está justamente no cenário em que ninguém percebe nada: sem SMTP,
o e-mail de redefinição some no log e a API responde 200 do mesmo jeito. Por
isso o teste checa que a falha aparece — e que ela não atrapalha em DEBUG.
"""

import pytest

from apps.common.checks import (
    CONSOLE,
    cobranca_precisa_de_gateway_real,
    criptografia_do_smtp_coerente,
    email_precisa_sair_da_maquina,
    estaticos_precisam_estar_coletados,
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
    @pytest.mark.parametrize("hosts", [["*"], ["app.batimento.com.br", "*"]])
    def test_curinga_em_producao_e_erro(self, settings, hosts):
        settings.DEBUG = False
        settings.ALLOWED_HOSTS = hosts
        assert ids(hosts_precisam_ser_explicitos(None)) == ["finfam.E002"]

    def test_dominio_explicito_passa(self, settings):
        settings.DEBUG = False
        settings.ALLOWED_HOSTS = ["app.batimento.com.br"]
        assert hosts_precisam_ser_explicitos(None) == []


class TestCriptografiaDoSmtp:
    """As duas portas que a Hostinger publica, e os dois jeitos de errar."""

    def _configurar(self, settings, porta, ssl, tls):
        settings.EMAIL_HOST = "smtp.hostinger.com"
        settings.EMAIL_PORT = porta
        settings.EMAIL_USE_SSL = ssl
        settings.EMAIL_USE_TLS = tls

    def test_465_com_ssl_passa(self, settings):
        self._configurar(settings, 465, ssl=True, tls=False)
        assert criptografia_do_smtp_coerente(None) == []

    def test_587_com_starttls_passa(self, settings):
        self._configurar(settings, 587, ssl=False, tls=True)
        assert criptografia_do_smtp_coerente(None) == []

    def test_as_duas_ligadas_e_erro(self, settings):
        self._configurar(settings, 465, ssl=True, tls=True)
        assert ids(criptografia_do_smtp_coerente(None)) == ["finfam.E003"]

    def test_nenhuma_ligada_e_erro(self, settings):
        self._configurar(settings, 25, ssl=False, tls=False)
        assert ids(criptografia_do_smtp_coerente(None)) == ["finfam.E004"]

    def test_sem_smtp_a_verificacao_se_cala(self, settings):
        """Em desenvolvimento não há host: não há o que verificar."""
        self._configurar(settings, 587, ssl=False, tls=False)
        settings.EMAIL_HOST = ""
        assert criptografia_do_smtp_coerente(None) == []


class TestEstaticos:
    """Sem o manifesto, o /admin/ responde 500 — não fica só sem estilo."""

    def test_sem_manifesto_em_producao_e_erro(self, settings, tmp_path):
        settings.DEBUG = False
        settings.STATIC_ROOT = tmp_path / "vazio"
        assert ids(estaticos_precisam_estar_coletados(None)) == ["finfam.E005"]

    def test_com_manifesto_passa(self, settings, tmp_path):
        settings.DEBUG = False
        settings.STATIC_ROOT = tmp_path
        (tmp_path / "staticfiles.json").write_text("{}")
        assert estaticos_precisam_estar_coletados(None) == []

    def test_em_desenvolvimento_nao_atrapalha(self, settings, tmp_path):
        settings.DEBUG = True
        settings.STATIC_ROOT = tmp_path / "vazio"
        assert estaticos_precisam_estar_coletados(None) == []


class TestGateway:
    def test_mock_em_producao_avisa(self, settings):
        settings.DEBUG = False
        settings.ASSINATURA_GATEWAY = "apps.billing.gateways_stripe.GatewayStripeMock"
        assert ids(cobranca_precisa_de_gateway_real(None)) == ["finfam.W001"]

    def test_gateway_real_passa(self, settings):
        settings.DEBUG = False
        settings.ASSINATURA_GATEWAY = "apps.billing.gateways_stripe.GatewayStripe"
        assert cobranca_precisa_de_gateway_real(None) == []


class TestSondaDeSaude:
    """A sonda do contêiner precisa passar pela validação de Host do Django.

    Ela consulta http://localhost:8000/api/saude/ de dentro do próprio
    contêiner. Sem `localhost` na lista, o Django responde 400, o Docker marca
    o serviço como doente, e a aplicação segue atendendo normalmente quem vem
    de fora — que é o pior tipo de alarme: o que aponta para o lugar errado.
    """

    def test_localhost_e_sempre_aceito(self, settings):
        assert "localhost" in settings.ALLOWED_HOSTS
        assert "127.0.0.1" in settings.ALLOWED_HOSTS

    @pytest.mark.django_db
    def test_a_sonda_responde(self, client):
        resposta = client.get("/api/saude/", HTTP_HOST="localhost:8000")

        assert resposta.status_code == 200
        assert resposta.json() == {"status": "ok"}

    @pytest.mark.django_db
    def test_host_desconhecido_continua_recusado(self, client, settings):
        """Liberar a sonda não pode liberar qualquer domínio."""
        settings.ALLOWED_HOSTS = ["batimento.com.br", "localhost", "127.0.0.1"]

        resposta = client.get("/api/saude/", HTTP_HOST="site-de-terceiro.com")
        assert resposta.status_code == 400
