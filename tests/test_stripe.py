"""Gateway Stripe e os três planos.

O mock herda da classe real, então estes testes exercitam a tradução de eventos
e as transições de estado que vão valer em produção — só a chamada de rede é
simulada. Quando a chave do Stripe entrar, o que muda é uma linha de settings.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.billing.gateways import assinatura_do_household, gateway_atual
from apps.billing.gateways_stripe import GatewayStripe, GatewayStripeMock
from apps.billing.models import Plan, StatusAssinatura

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture(autouse=True)
def sessoes_limpas():
    GatewayStripeMock.sessoes = []
    yield
    GatewayStripeMock.sessoes = []


class TestCatalogoDePlanos:
    def test_tres_planos_com_os_precos_definidos(self, api, familia_autenticada):
        planos = {p["codigo"]: p for p in api.get(reverse("planos")).data}

        assert D(planos["basico"]["preco_promocional"]) == D("39.90")
        assert D(planos["basico"]["preco_mensal"]) == D("49.90")
        assert planos["basico"]["meses_promocionais"] == 6

        assert D(planos["intermediario"]["preco_promocional"]) == D("80.90")
        assert D(planos["intermediario"]["preco_mensal"]) == D("99.00")
        assert planos["intermediario"]["meses_promocionais"] == 3

        assert D(planos["consultor"]["preco_promocional"]) == D("499.90")
        assert D(planos["consultor"]["preco_mensal"]) == D("599.90")
        assert planos["consultor"]["meses_promocionais"] == 6

    def test_somente_o_basico_pode_ser_assinado_agora(self, api, familia_autenticada):
        planos = {p["codigo"]: p for p in api.get(reverse("planos")).data}

        assert planos["basico"]["disponivel"] is True
        assert planos["intermediario"]["disponivel"] is False
        assert planos["consultor"]["disponivel"] is False

    def test_preco_de_entrada_e_o_promocional(self):
        basico = Plan.objects.get(codigo="basico")
        assert basico.em_promocao is True
        assert basico.preco_de_entrada == D("39.90")

    def test_recursos_marcam_o_que_ainda_nao_existe(self, api, familia_autenticada):
        planos = {p["codigo"]: p for p in api.get(reverse("planos")).data}

        analise_ia = [
            recurso
            for recurso in planos["intermediario"]["recursos"]
            if "IA" in recurso["texto"]
        ]
        assert analise_ia and analise_ia[0]["em_breve"] is True

        consultor = planos["consultor"]["recursos"]
        assert any("Consultor" in r["texto"] and r["em_breve"] for r in consultor)
        assert any("Contabilidade" in r["texto"] for r in consultor)


class TestCheckout:
    def test_basico_gera_url_de_pagamento(self, api, familia_autenticada):
        household, _, _ = familia_autenticada

        resposta = api.post(reverse("checkout"), {"plano": "basico"}, format="json")

        assert resposta.status_code == 200
        assert resposta.data["plano"] == "basico"
        assert resposta.data["url"]

        # O plano escolhido fica registrado antes do pagamento.
        assert assinatura_do_household(household).plano.codigo == "basico"

    def test_parametros_enviados_ao_stripe(self, api, familia_autenticada):
        household, _, _ = familia_autenticada
        api.post(reverse("checkout"), {"plano": "basico"}, format="json")

        parametros = GatewayStripeMock.sessoes[-1]
        assinatura = assinatura_do_household(household)

        assert parametros["mode"] == "subscription"
        assert parametros["locale"] == "pt-BR"
        # A referência é o que permite achar a assinatura quando o evento voltar.
        assert parametros["client_reference_id"] == str(assinatura.id)
        assert parametros["subscription_data"]["metadata"]["assinatura_id"] == str(assinatura.id)

    @pytest.mark.parametrize("codigo", ["intermediario", "consultor"])
    def test_plano_em_breve_e_recusado_pelo_servidor(self, api, familia_autenticada, codigo):
        """Bloquear só na interface deixaria a API aberta a quem chamar direto."""
        resposta = api.post(reverse("checkout"), {"plano": codigo}, format="json")

        assert resposta.status_code == 400
        assert "não está disponível" in str(resposta.data)
        assert GatewayStripeMock.sessoes == []

    def test_plano_inexistente_responde_404(self, api, familia_autenticada):
        assert api.post(reverse("checkout"), {"plano": "premium"}, format="json").status_code == 404

    def test_exige_autenticacao(self, api):
        assert api.post(reverse("checkout"), {"plano": "basico"}, format="json").status_code == 401

    def test_quem_ja_paga_nao_abre_um_segundo_checkout(self, api, familia_autenticada):
        """Dois checkouts viram duas assinaturas no Stripe — e cobrança dobrada."""
        household, _, _ = familia_autenticada
        assinatura = assinatura_do_household(household)
        gateway_atual().confirmar_pagamento(assinatura)
        GatewayStripeMock.sessoes = []

        resposta = api.post(reverse("checkout"), {"plano": "basico"}, format="json")

        assert resposta.status_code == 400
        assert "já tem uma assinatura ativa" in str(resposta.data)
        assert "portal" in str(resposta.data)
        assert GatewayStripeMock.sessoes == []

    def test_quem_esta_em_teste_ainda_pode_assinar(self, api, familia_autenticada):
        """O bloqueio acima não pode fechar a porta de quem ainda vai pagar."""
        assert api.post(reverse("checkout"), {"plano": "basico"}, format="json").status_code == 200

    def test_plano_sem_price_no_stripe_falha_com_mensagem_util(self, familia_autenticada):
        """Trocar para o gateway real sem cadastrar o Price é erro de operação."""
        household, _, _ = familia_autenticada
        assinatura = assinatura_do_household(household)
        plano = Plan.objects.get(codigo="basico")
        assert plano.stripe_price_id == "", "o cenário exige o Price ainda em branco"

        with pytest.raises(ValueError, match="stripe_price_id"):
            GatewayStripe().criar_checkout(assinatura, plano, "https://app/retorno")


class TestEventosDoStripe:
    def _evento(self, tipo, assinatura, **extras):
        return {
            "type": tipo,
            "data": {
                "object": {
                    "client_reference_id": str(assinatura.id),
                    "customer": "cus_123",
                    "subscription": "sub_123",
                    **extras,
                }
            },
        }

    def test_checkout_concluido_ativa_e_guarda_os_ids(self, api, familia_autenticada):
        household, _, _ = familia_autenticada
        api.post(reverse("checkout"), {"plano": "basico"}, format="json")
        assinatura = assinatura_do_household(household)

        GatewayStripeMock().processar_evento(
            self._evento("checkout.session.completed", assinatura)
        )

        assinatura.refresh_from_db()
        assert assinatura.status == StatusAssinatura.ATIVA
        assert assinatura.gateway == "stripe"
        assert assinatura.gateway_customer_id == "cus_123"
        assert assinatura.gateway_subscription_id == "sub_123"
        assert assinatura.da_acesso is True

    def test_checkout_concluido_marca_o_fim_da_promocao(self, api, familia_autenticada):
        household, _, _ = familia_autenticada
        api.post(reverse("checkout"), {"plano": "basico"}, format="json")
        assinatura = assinatura_do_household(household)

        GatewayStripeMock().processar_evento(
            self._evento("checkout.session.completed", assinatura)
        )

        assinatura.refresh_from_db()
        # Seis meses promocionais no Básico.
        assert assinatura.promocao_ate is not None
        assert assinatura.promocao_ate > date.today()

    def test_pagamento_falho_abre_carencia_em_vez_de_cortar(self, api, familia_autenticada):
        household, _, _ = familia_autenticada
        assinatura = assinatura_do_household(household)
        assinatura.ativar()

        GatewayStripeMock().processar_evento(self._evento("invoice.payment_failed", assinatura))

        assinatura.refresh_from_db()
        assert assinatura.status == StatusAssinatura.INADIMPLENTE
        assert assinatura.da_acesso is True  # ainda entra, com aviso

    def test_pagamento_confirmado_reativa(self, api, familia_autenticada):
        household, _, _ = familia_autenticada
        assinatura = assinatura_do_household(household)
        assinatura.iniciar_carencia()

        GatewayStripeMock().processar_evento(
            self._evento("invoice.payment_succeeded", assinatura, period_end=1900000000)
        )

        assinatura.refresh_from_db()
        assert assinatura.status == StatusAssinatura.ATIVA
        assert assinatura.carencia_ate is None

    def test_assinatura_removida_no_stripe_cancela(self, api, familia_autenticada):
        household, _, _ = familia_autenticada
        assinatura = assinatura_do_household(household)
        assinatura.ativar()

        GatewayStripeMock().processar_evento(
            self._evento("customer.subscription.deleted", assinatura)
        )

        assinatura.refresh_from_db()
        assert assinatura.status == StatusAssinatura.CANCELADA
        assert assinatura.da_acesso is False

    def test_evento_de_assinatura_desconhecida_e_ignorado(self):
        resultado = GatewayStripeMock().processar_evento(
            {"type": "checkout.session.completed", "data": {"object": {"customer": "cus_zzz"}}}
        )
        assert resultado is None

    def test_localiza_pelo_id_do_stripe_quando_falta_referencia(self, api, familia_autenticada):
        household, _, _ = familia_autenticada
        assinatura = assinatura_do_household(household)
        assinatura.gateway_subscription_id = "sub_abc"
        assinatura.save()

        encontrada = GatewayStripeMock().processar_evento(
            {
                "type": "invoice.payment_failed",
                "data": {"object": {"subscription": "sub_abc"}},
            }
        )
        assert encontrada is not None
        assert encontrada.id == assinatura.id


class TestWebhook:
    def test_recusa_evento_sem_segredo_configurado(self, api, settings):
        """Sem segredo, o endereço viraria um botão de liberar acesso."""
        settings.STRIPE_WEBHOOK_SECRET = ""

        resposta = api.post(
            reverse("webhook-assinatura"), {"type": "invoice.payment_failed"}, format="json"
        )
        assert resposta.status_code == 503

    def test_processa_evento_quando_configurado(self, api, familia_autenticada, settings):
        settings.STRIPE_WEBHOOK_SECRET = "whsec_teste"
        household, _, _ = familia_autenticada
        assinatura = assinatura_do_household(household)
        assinatura.ativar()

        api.force_authenticate(user=None)
        resposta = api.post(
            reverse("webhook-assinatura"),
            {
                "type": "invoice.payment_failed",
                "data": {"object": {"client_reference_id": str(assinatura.id)}},
            },
            format="json",
        )

        assert resposta.status_code == 200
        assert resposta.data["processado"] is True
        assinatura.refresh_from_db()
        assert assinatura.status == StatusAssinatura.INADIMPLENTE

    def test_webhook_nao_exige_login(self, api, settings):
        """Quem chama é o Stripe, não o navegador do cliente."""
        settings.STRIPE_WEBHOOK_SECRET = "whsec_teste"
        api.force_authenticate(user=None)

        resposta = api.post(reverse("webhook-assinatura"), {"type": "ping"}, format="json")
        assert resposta.status_code == 200


class TestTrocaDeGateway:
    def test_padrao_e_o_mock(self):
        assert isinstance(gateway_atual(), GatewayStripeMock)

    def test_mock_herda_a_classe_real(self):
        """Garante que a lógica testada aqui é a mesma que rodará em produção."""
        assert issubclass(GatewayStripeMock, GatewayStripe)

    def test_reverter_e_uma_linha_de_configuracao(self, settings):
        settings.ASSINATURA_GATEWAY = "apps.billing.gateways_stripe.GatewayStripe"
        gateway = gateway_atual()

        assert isinstance(gateway, GatewayStripe)
        assert not isinstance(gateway, GatewayStripeMock)

    def test_portal_exige_cliente_no_stripe(self, api, familia_autenticada):
        resposta = api.post(reverse("portal-assinatura"), format="json")
        assert resposta.status_code == 400
        assert "cliente no Stripe" in str(resposta.data)

    def test_portal_funciona_depois_do_checkout(self, api, familia_autenticada):
        household, _, _ = familia_autenticada
        api.post(reverse("checkout"), {"plano": "basico"}, format="json")
        assinatura = assinatura_do_household(household)
        GatewayStripeMock().confirmar_pagamento(assinatura)

        resposta = api.post(reverse("portal-assinatura"), format="json")
        assert resposta.status_code == 200
        assert resposta.data["url"]
