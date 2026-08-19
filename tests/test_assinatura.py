"""Assinatura: teste grátis, carência e bloqueio.

O comportamento que mais importa não é liberar quem pagou — é o que acontece
com quem está no limite: o teste que acabou ontem, a cobrança que falhou hoje,
a carência que vence amanhã.
"""

from datetime import date, timedelta

import pytest
from django.urls import reverse

from apps.billing.gateways import (
    GatewayManual,
    assinatura_do_household,
    criar_assinatura_em_teste,
    encerrar_periodos_vencidos,
    gateway_atual,
)
from apps.billing.models import Plan, StatusAssinatura, Subscription

pytestmark = pytest.mark.django_db


def _assinatura(household, **campos):
    padrao = {
        "household": household,
        "tenant": household.tenant,
        "status": StatusAssinatura.TRIAL,
        "inicio": date.today(),
        "trial_termina_em": date.today() + timedelta(days=14),
    }
    return Subscription.objects.create(**{**padrao, **campos})


class TestCadastroCriaTeste:
    def test_conta_nova_nasce_em_periodo_de_teste(self, api, tenant_plataforma, settings):
        settings.ASSINATURA_TRIAL_DIAS = 14

        api.post(
            reverse("signup"),
            {
                "email": "nova@exemplo.com",
                "password": "senha-muito-segura-123",
                "nome_completo": "Nova Médica",
            },
            format="json",
        )

        assinatura = Subscription.objects.get()
        assert assinatura.status == StatusAssinatura.TRIAL
        assert assinatura.trial_termina_em == date.today() + timedelta(days=14)
        assert assinatura.da_acesso is True

    def test_usa_o_plano_self_service(self, api, tenant_plataforma):
        Plan.objects.get_or_create(
            codigo="self_service", defaults={"nome": "Pulso", "preco_mensal": 97}
        )
        api.post(
            reverse("signup"),
            {
                "email": "outra@exemplo.com",
                "password": "senha-muito-segura-123",
                "nome_completo": "Outra Médica",
            },
            format="json",
        )
        assert Subscription.objects.get().plano.codigo == "self_service"


class TestRegraDeAcesso:
    def test_teste_valido_da_acesso(self, familia_autenticada):
        household, _, _ = familia_autenticada
        assinatura = _assinatura(household)
        assert assinatura.da_acesso is True
        assert assinatura.em_teste is True
        assert assinatura.dias_restantes == 14

    def test_teste_vencido_bloqueia(self, familia_autenticada):
        household, _, _ = familia_autenticada
        assinatura = _assinatura(household, trial_termina_em=date.today() - timedelta(days=1))

        assert assinatura.da_acesso is False
        assert "teste terminou" in assinatura.motivo_do_bloqueio
        assert assinatura.dias_restantes == 0

    def test_ultimo_dia_do_teste_ainda_vale(self, familia_autenticada):
        """Quem tem até hoje, tem hoje inteiro."""
        household, _, _ = familia_autenticada
        assinatura = _assinatura(household, trial_termina_em=date.today())
        assert assinatura.da_acesso is True

    def test_carencia_mantem_o_acesso(self, familia_autenticada):
        household, _, _ = familia_autenticada
        assinatura = _assinatura(
            household,
            status=StatusAssinatura.INADIMPLENTE,
            carencia_ate=date.today() + timedelta(days=3),
        )

        assert assinatura.da_acesso is True
        assert assinatura.em_carencia is True
        assert assinatura.dias_restantes == 3

    def test_carencia_vencida_bloqueia(self, familia_autenticada):
        household, _, _ = familia_autenticada
        assinatura = _assinatura(
            household,
            status=StatusAssinatura.INADIMPLENTE,
            carencia_ate=date.today() - timedelta(days=1),
        )
        assert assinatura.da_acesso is False
        assert "pagamento" in assinatura.motivo_do_bloqueio

    @pytest.mark.parametrize(
        "status", [StatusAssinatura.SUSPENSA, StatusAssinatura.CANCELADA]
    )
    def test_suspensa_e_cancelada_bloqueiam(self, familia_autenticada, status):
        household, _, _ = familia_autenticada
        assinatura = _assinatura(household, status=status, trial_termina_em=None)
        assert assinatura.da_acesso is False

    def test_ativa_da_acesso_sem_prazo(self, familia_autenticada):
        household, _, _ = familia_autenticada
        assinatura = _assinatura(household, status=StatusAssinatura.ATIVA, trial_termina_em=None)
        assert assinatura.da_acesso is True
        assert assinatura.dias_restantes is None


class TestTransicoes:
    def test_cobranca_falha_abre_carencia(self, familia_autenticada, settings):
        settings.ASSINATURA_CARENCIA_DIAS = 5
        household, _, _ = familia_autenticada
        assinatura = _assinatura(household, status=StatusAssinatura.ATIVA)

        assinatura.iniciar_carencia()

        assert assinatura.status == StatusAssinatura.INADIMPLENTE
        assert assinatura.carencia_ate == date.today() + timedelta(days=5)
        assert assinatura.da_acesso is True

    def test_pagamento_confirmado_limpa_a_carencia(self, familia_autenticada):
        household, _, _ = familia_autenticada
        assinatura = _assinatura(
            household,
            status=StatusAssinatura.INADIMPLENTE,
            carencia_ate=date.today() + timedelta(days=2),
        )

        assinatura.ativar(proxima_cobranca=date.today() + timedelta(days=30))

        assert assinatura.status == StatusAssinatura.ATIVA
        assert assinatura.carencia_ate is None
        assert assinatura.da_acesso is True

    def test_cancelar_preserva_a_data(self, familia_autenticada):
        household, _, _ = familia_autenticada
        assinatura = _assinatura(household)
        assinatura.cancelar()

        assert assinatura.status == StatusAssinatura.CANCELADA
        assert assinatura.cancelada_em == date.today()


class TestRotinaDiaria:
    def test_suspende_testes_e_carencias_vencidos(self, familia, familia_autenticada):
        household_a, _, _ = familia_autenticada
        household_b, _, _ = familia(email="b@exemplo.com", nome="B", nome_familia="Família B")

        vencida = _assinatura(household_a, trial_termina_em=date.today() - timedelta(days=1))
        carencia = _assinatura(
            household_b,
            status=StatusAssinatura.INADIMPLENTE,
            carencia_ate=date.today() - timedelta(days=1),
        )

        resultado = encerrar_periodos_vencidos()

        vencida.refresh_from_db()
        carencia.refresh_from_db()
        assert resultado == {"trials_encerrados": 1, "carencias_encerradas": 1}
        assert vencida.status == StatusAssinatura.SUSPENSA
        assert carencia.status == StatusAssinatura.SUSPENSA

    def test_nao_mexe_em_quem_esta_em_dia(self, familia_autenticada):
        household, _, _ = familia_autenticada
        valida = _assinatura(household)

        encerrar_periodos_vencidos()

        valida.refresh_from_db()
        assert valida.status == StatusAssinatura.TRIAL

    def test_rodar_duas_vezes_nao_muda_nada(self, familia_autenticada):
        household, _, _ = familia_autenticada
        _assinatura(household, trial_termina_em=date.today() - timedelta(days=1))

        encerrar_periodos_vencidos()
        segunda = encerrar_periodos_vencidos()

        assert segunda == {"trials_encerrados": 0, "carencias_encerradas": 0}


class TestBloqueioNaApi:
    def _bloquear(self, household):
        Subscription.objects.filter(household=household).delete()
        return _assinatura(
            household, status=StatusAssinatura.SUSPENSA, trial_termina_em=None
        )

    def test_tela_paga_responde_402(self, api, familia_autenticada):
        household, _, _ = familia_autenticada
        self._bloquear(household)

        resposta = api.get(reverse("dashboard"))

        assert resposta.status_code == 402
        assert "assinatura" in str(resposta.data["detail"]).lower()

    def test_bloqueio_vale_para_escrita(self, api, familia_autenticada):
        household, _, _ = familia_autenticada
        self._bloquear(household)

        resposta = api.post(
            reverse("meta-list"), {"descricao": "Meta", "valor_alvo": "1000"}, format="json"
        )
        assert resposta.status_code == 402

    def test_dados_do_usuario_continuam_acessiveis(self, api, familia_autenticada):
        """Quem está bloqueado precisa entrar para entender e resolver."""
        household, _, _ = familia_autenticada
        self._bloquear(household)

        assert api.get(reverse("me")).status_code == 200
        assert api.get(reverse("assinatura")).status_code == 200

    def test_teste_valido_nao_bloqueia(self, api, familia_autenticada):
        assert api.get(reverse("dashboard")).status_code == 200


class TestEndpointDeAssinatura:
    def test_expoe_o_estado_para_a_tela(self, api, familia_autenticada):
        household, _, _ = familia_autenticada
        Subscription.objects.filter(household=household).delete()
        _assinatura(household, trial_termina_em=date.today() + timedelta(days=3))

        dados = api.get(reverse("assinatura")).data

        assert dados["possui_assinatura"] is True
        assert dados["em_teste"] is True
        assert dados["dias_restantes"] == 3
        assert dados["da_acesso"] is True
        # Sem gateway configurado, a tela não deve oferecer checkout.
        assert dados["cobranca_automatica"] is False

    def test_informa_o_motivo_quando_bloqueado(self, api, familia_autenticada):
        household, _, _ = familia_autenticada
        Subscription.objects.filter(household=household).delete()
        _assinatura(household, status=StatusAssinatura.CANCELADA, trial_termina_em=None)

        dados = api.get(reverse("assinatura")).data
        assert dados["da_acesso"] is False
        assert "cancelada" in dados["motivo_do_bloqueio"].lower()

    def test_exige_autenticacao(self, api):
        assert api.get(reverse("assinatura")).status_code == 401


class TestDadosFiscais:
    def test_guarda_documento_apenas_com_digitos(self, api, familia_autenticada):
        resposta = api.patch(
            reverse("dados-fiscais"),
            {"documento": "123.456.789-09", "cidade": "São Paulo", "uf": "SP"},
            format="json",
        )
        assert resposta.status_code == 200
        assert resposta.data["documento"] == "12345678909"

    def test_recusa_documento_invalido(self, api, familia_autenticada):
        resposta = api.patch(reverse("dados-fiscais"), {"documento": "123"}, format="json")
        assert resposta.status_code == 400

    def test_sinaliza_quando_falta_dado_para_a_nota(self, api, familia_autenticada):
        parcial = api.patch(
            reverse("dados-fiscais"), {"documento": "12345678909"}, format="json"
        )
        assert parcial.data["completo"] is False

        completo = api.patch(
            reverse("dados-fiscais"),
            {
                "documento": "12345678909",
                "cep": "01310-100",
                "logradouro": "Av. Paulista",
                "numero": "1000",
                "cidade": "São Paulo",
                "uf": "SP",
            },
            format="json",
        )
        assert completo.data["completo"] is True


class TestGateway:
    def test_padrao_e_cobranca_manual(self):
        assert isinstance(gateway_atual(), GatewayManual)

    def test_manual_recusa_checkout_em_vez_de_inventar_url(self, familia_autenticada):
        """Devolver uma URL falsa levaria o cliente a uma página quebrada."""
        household, _, _ = familia_autenticada
        assinatura = criar_assinatura_em_teste(household)

        with pytest.raises(NotImplementedError, match="Nenhum gateway"):
            gateway_atual().criar_checkout(assinatura, assinatura.plano, "https://app/retorno")

    def test_assinatura_do_household_traz_a_mais_recente(self, familia_autenticada):
        household, _, _ = familia_autenticada
        Subscription.objects.filter(household=household).delete()
        _assinatura(household, status=StatusAssinatura.CANCELADA)
        atual = _assinatura(household, status=StatusAssinatura.ATIVA)

        assert assinatura_do_household(household).id == atual.id
