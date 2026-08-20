"""O admin de cobrança.

Existe porque os identificadores do Stripe nascem no painel deles e precisam
ser transcritos para cá — é o único ponto de encontro entre os dois catálogos.
Sem esta tela, o passo de ligar preço e cupom simplesmente não tem onde
acontecer, e a integração inteira fica sem saída.

Os testes abaixo não conferem aparência: conferem que a tela abre, que os
campos do Stripe estão nela e que dá para gravar.
"""

import pytest
from django.urls import reverse

from apps.billing.models import Plan

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_logado(client, django_user_model):
    admin = django_user_model.objects.create_superuser(
        email="admin@exemplo.com", password="senha-de-admin-123456"
    )
    client.force_login(admin)
    return client


class TestPlanoNoAdmin:
    def test_a_lista_de_planos_abre(self, admin_logado):
        resposta = admin_logado.get(reverse("admin:billing_plan_changelist"))
        assert resposta.status_code == 200

    def test_os_tres_planos_aparecem(self, admin_logado):
        conteudo = admin_logado.get(reverse("admin:billing_plan_changelist")).content.decode()
        for nome in ("Básico", "Intermediário", "Com consultor"):
            assert nome in conteudo

    def test_a_edicao_traz_os_campos_do_stripe(self, admin_logado):
        """Se estes dois campos não estiverem na tela, não há como cobrar."""
        plano = Plan.objects.get(codigo="basico")
        conteudo = admin_logado.get(
            reverse("admin:billing_plan_change", args=[plano.pk])
        ).content.decode()

        assert "stripe_price_id" in conteudo
        assert "stripe_coupon_id" in conteudo

    def test_a_tela_explica_de_onde_vem_o_identificador(self, admin_logado):
        # Quem preenche isso vai estar com dois painéis abertos e sem saber
        # qual dos números copiar.
        plano = Plan.objects.get(codigo="basico")
        conteudo = admin_logado.get(
            reverse("admin:billing_plan_change", args=[plano.pk])
        ).content.decode()

        assert "price_" in conteudo
        assert "produção" in conteudo

    def test_grava_os_identificadores(self, admin_logado):
        plano = Plan.objects.get(codigo="basico")

        resposta = admin_logado.post(
            reverse("admin:billing_plan_change", args=[plano.pk]),
            {
                "codigo": plano.codigo,
                "nome": plano.nome,
                "descricao": plano.descricao,
                "ordem": plano.ordem,
                "preco_mensal": "49.90",
                "preco_promocional": "39.90",
                "meses_promocionais": 6,
                "preco_anual": "",
                "ativo": "on",
                "disponivel": "on",
                "recursos": "[]",
                "stripe_price_id": "price_1ABCdef",
                "stripe_coupon_id": "PROMO6MESES",
            },
        )

        assert resposta.status_code == 302, resposta.context["adminform"].form.errors
        plano.refresh_from_db()
        assert plano.stripe_price_id == "price_1ABCdef"
        assert plano.stripe_coupon_id == "PROMO6MESES"

    def test_a_lista_mostra_quem_ainda_nao_cobra(self, admin_logado):
        """Plano disponível sem price é venda que falha na hora do pagamento."""
        from apps.billing.admin import PlanAdmin

        plano = Plan.objects.get(codigo="basico")
        assert PlanAdmin.conectado_ao_stripe(None, plano) is False

        plano.stripe_price_id = "price_1ABCdef"
        assert PlanAdmin.conectado_ao_stripe(None, plano) is True


class TestAssinaturaNoAdmin:
    def test_a_lista_abre(self, admin_logado, familia):
        resposta = admin_logado.get(reverse("admin:billing_subscription_changelist"))
        assert resposta.status_code == 200

    def test_mostra_o_motivo_do_bloqueio(self, admin_logado, familia):
        """A pergunta de suporte é sempre "por que este cliente não entra?"."""
        from apps.billing.admin import SubscriptionAdmin
        from apps.billing.gateways import criar_assinatura_em_teste

        household, _, _ = familia(email="x@exemplo.com", nome="X", nome_familia="Família X")
        assinatura = criar_assinatura_em_teste(household)

        assert SubscriptionAdmin.acesso(None, assinatura) is True
        assert "acesso liberado" in SubscriptionAdmin.motivo_do_bloqueio_exibido(None, assinatura)
