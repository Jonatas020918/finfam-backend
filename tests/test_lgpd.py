"""Direitos do titular sobre os próprios dados.

Três coisas precisam ser verdade, e nenhuma delas é verificável olhando o
código: que o consentimento fica registrado de forma utilizável como prova,
que a exportação traz tudo, e que a exclusão apaga de fato — preservando só o
que a lei manda preservar.

O caso que mais importa é o último. Uma exclusão que diz ter apagado e não
apagou é pior que não oferecer o recurso: cria registro de cumprimento para
algo que não aconteceu.
"""

import json

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.billing.models import DadosFiscais, Subscription
from apps.cashflow.models import CashFlowEntry
from apps.households.models import Asset, Debt, Household, IncomeSource, Member

pytestmark = pytest.mark.django_db

SENHA = "senha-muito-segura-123"


def _cadastrar(api, email="titular@exemplo.com", **extras):
    corpo = {
        "email": email,
        "password": SENHA,
        "nome_completo": "Dra. Titular",
        "aceite_termos": True,
        **extras,
    }
    return api.post(reverse("signup"), corpo, format="json")


class TestAceiteNoCadastro:
    def test_sem_aceite_o_cadastro_e_recusado(self, api, tenant_plataforma):
        resposta = _cadastrar(api, aceite_termos=False)

        assert resposta.status_code == 400
        assert "aceite_termos" in resposta.data
        assert not User.objects.filter(email="titular@exemplo.com").exists()

    def test_aceite_ausente_tambem_e_recusado(self, api, tenant_plataforma):
        """Omitir o campo não pode valer como aceitar."""
        resposta = api.post(
            reverse("signup"),
            {"email": "x@exemplo.com", "password": SENHA, "nome_completo": "X"},
            format="json",
        )
        assert resposta.status_code == 400

    def test_o_aceite_guarda_versao_data_e_origem(self, api, tenant_plataforma, settings):
        """"Aceitou: sim" não sustenta nada. A versão é o que dá validade."""
        settings.VERSAO_TERMOS = "2026.1"
        _cadastrar(api)

        usuario = User.objects.get(email="titular@exemplo.com")
        assert usuario.aceite_termos_versao == "2026.1"
        assert usuario.aceite_termos_em is not None
        assert usuario.aceite_termos_ip is not None

    def test_versao_nova_invalida_o_aceite_antigo(self, api, tenant_plataforma, settings):
        """Sem isto, revisar os termos deixaria todos concordando com um texto
        que ninguém leu."""
        settings.VERSAO_TERMOS = "2026.1"
        _cadastrar(api)
        usuario = User.objects.get(email="titular@exemplo.com")
        assert usuario.termos_aceitos is True

        settings.VERSAO_TERMOS = "2027.1"
        assert usuario.termos_aceitos is False

    def test_o_titular_pode_aceitar_a_versao_nova(self, api, familia_autenticada, settings):
        settings.VERSAO_TERMOS = "2027.1"

        resposta = api.post(reverse("aceitar-termos"))

        assert resposta.status_code == 200
        assert resposta.data["termos_aceitos"] is True

    def test_a_versao_em_vigor_e_publica(self, api, settings):
        """Quem ainda não tem conta precisa poder ler antes de criar uma."""
        settings.VERSAO_TERMOS = "2026.1"
        resposta = api.get(reverse("termos"))

        assert resposta.status_code == 200
        assert resposta.data["versao"] == "2026.1"
        assert "@" in resposta.data["encarregado_email"]


class TestExportacao:
    def test_exige_autenticacao(self, api):
        assert api.get(reverse("exportar-dados")).status_code == 401

    def test_vem_como_arquivo_para_download(self, api, familia_autenticada):
        """O titular precisa guardar isto, não só ver na tela."""
        resposta = api.get(reverse("exportar-dados"))

        assert resposta.status_code == 200
        assert "attachment" in resposta["Content-Disposition"]
        assert "batimento-meus-dados" in resposta["Content-Disposition"]

    def test_traz_todas_as_categorias_de_dado(self, api, familia_autenticada):
        household, _, _ = familia_autenticada
        IncomeSource.objects.create(
            household=household, tenant=household.tenant, membro=household.membros.first(),
            descricao="Plantões", tipo="plantao", regime="pj", valor_medio_mensal="20000",
        )
        Asset.objects.create(
            household=household, tenant=household.tenant,
            descricao="Apartamento", tipo="imovel", valor_atual="800000",
        )

        dados = json.loads(api.get(reverse("exportar-dados")).content)

        assert dados["titular"]["email"]
        assert dados["nucleo_familiar"]["nome"]
        assert any(f["descricao"] == "Plantões" for f in dados["fontes_de_renda"])
        assert any(p["descricao"] == "Apartamento" for p in dados["patrimonio"])
        # Todas as chaves previstas existem, mesmo vazias: ausência de seção
        # deixaria o titular sem saber se o dado não existe ou não foi enviado.
        for secao in ("membros", "dividas", "objetivos", "metas", "lancamentos", "assinatura"):
            assert secao in dados

    def test_o_arquivo_explica_o_que_e(self, api, familia_autenticada):
        dados = json.loads(api.get(reverse("exportar-dados")).content)
        assert "LGPD" in dados["aviso"]

    def test_nao_vaza_dado_de_outra_familia(self, api, familia, familia_autenticada):
        outro, _, _ = familia(
            email="outro@exemplo.com", nome="Outro", nome_familia="Família Vizinha"
        )
        Asset.objects.create(
            household=outro, tenant=outro.tenant,
            descricao="Casa do vizinho", tipo="imovel", valor_atual="1",
        )

        dados = json.loads(api.get(reverse("exportar-dados")).content)

        assert not any(p["descricao"] == "Casa do vizinho" for p in dados["patrimonio"])


class TestExclusao:
    def _povoar(self, household):
        Member.objects.create(household=household, tenant=household.tenant, nome="Cônjuge", tipo="conjuge")
        Asset.objects.create(
            household=household, tenant=household.tenant,
            descricao="Apartamento", tipo="imovel", valor_atual="800000",
        )
        Debt.objects.create(
            household=household, tenant=household.tenant,
            descricao="Financiamento", tipo="financiamento_imovel", saldo_devedor="400000",
        )
        CashFlowEntry.objects.create(
            household=household, tenant=household.tenant, ano=2026, mes=8,
            tipo="receita", categoria="renda_trabalho", descricao="Salário",
            valor_realizado="20000",
        )
        DadosFiscais.objects.create(household=household, documento="12345678909")

    def test_exige_autenticacao(self, api):
        assert api.delete(reverse("excluir-conta")).status_code == 401

    def test_exige_a_senha(self, api, familia_autenticada):
        """A ação é irreversível: um clique acidental não pode bastar."""
        resposta = api.delete(reverse("excluir-conta"), {}, format="json")

        assert resposta.status_code == 400
        # Lista, como todo erro de campo do DRF: a tela lê o primeiro item, e
        # uma string solta faria aparecer só a primeira letra da mensagem.
        assert resposta.data["senha"] == ["Senha incorreta. A exclusão não foi realizada."]

    def test_senha_errada_nao_apaga_nada(self, api, familia_autenticada):
        household, _, usuario = familia_autenticada
        self._povoar(household)

        resposta = api.delete(reverse("excluir-conta"), {"senha": "chute"}, format="json")

        assert resposta.status_code == 400
        assert User.objects.filter(pk=usuario.pk).exists()
        assert Asset.objects.filter(household=household).exists()

    def test_apaga_os_dados_do_titular(self, api, familia_autenticada):
        household, _, usuario = familia_autenticada
        self._povoar(household)

        resposta = api.delete(reverse("excluir-conta"), {"senha": SENHA}, format="json")

        assert resposta.status_code == 200
        assert resposta.data["excluida"] is True

        assert not User.objects.filter(pk=usuario.pk).exists()
        assert not Member.objects.filter(household=household).exists()
        assert not Asset.objects.filter(household=household).exists()
        assert not Debt.objects.filter(household=household).exists()
        assert not CashFlowEntry.objects.filter(household=household).exists()
        assert not DadosFiscais.objects.filter(household=household).exists()

    def test_preserva_o_rastro_de_cobranca_sem_identificar_ninguem(self, api, familia_autenticada):
        """O art. 16, I ressalva o que é obrigação legal manter.

        Um serviço que emitiu nota precisa guardar o registro da cobrança pelo
        prazo fiscal. O que não pode é esse registro continuar apontando para
        uma pessoa.
        """
        household, _, _ = familia_autenticada
        assinatura = Subscription.objects.filter(household=household).first()
        assinatura.gateway_customer_id = "cus_123"
        assinatura.gateway_subscription_id = "sub_123"
        assinatura.save()

        api.delete(reverse("excluir-conta"), {"senha": SENHA}, format="json")

        assinatura.refresh_from_db()
        assert assinatura.gateway_customer_id == ""
        assert assinatura.gateway_subscription_id == ""
        assert not DadosFiscais.objects.filter(household=household).exists()

        household.refresh_from_db()
        assert "excluído" in household.nome.lower()

    def test_nao_toca_em_outra_familia(self, api, familia, familia_autenticada):
        outro, _, outro_usuario = familia(
            email="outro@exemplo.com", nome="Outro", nome_familia="Família Vizinha"
        )
        self._povoar(outro)

        api.delete(reverse("excluir-conta"), {"senha": SENHA}, format="json")

        assert User.objects.filter(pk=outro_usuario.pk).exists()
        assert Asset.objects.filter(household=outro).count() == 1
        assert Household.objects.filter(pk=outro.pk).exists()

    def test_o_email_fica_livre_para_novo_cadastro(self, api, familia_autenticada, tenant_plataforma):
        """Excluir a conta precisa realmente liberar a identidade.

        Se o e-mail continuasse ocupado, a pessoa não conseguiria voltar — e o
        dado que a identifica seguiria guardado, que é o oposto do pedido.
        """
        _, _, usuario = familia_autenticada
        email = usuario.email

        api.delete(reverse("excluir-conta"), {"senha": SENHA}, format="json")

        assert not User.objects.filter(email=email).exists()
        resposta = _cadastrar(api, email=email)
        assert resposta.status_code == 201
