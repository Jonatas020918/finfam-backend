"""Dois números que o fluxo de caixa mostrava errados.

O primeiro era a renda CLT: entrava pelo bruto, como se não houvesse retenção
na fonte. Numa renda alta a diferença passa de um quarto do valor — o
suficiente para a taxa de poupança mentir e a projeção de patrimônio prometer
dinheiro que nunca existiu.

O segundo era a parcela do financiamento: a dívida era cadastrada no
onboarding e nunca aparecia como despesa. O fluxo mostrava as receitas
completas e escondia a maior saída fixa da família.

Os dois erram para o mesmo lado — saldo maior que o real —, que é o lado que
faz alguém tomar uma decisão que não podia tomar.
"""

from datetime import date
from decimal import Decimal as D

import pytest
from django.urls import reverse

from apps.cashflow.competencia import abrir_competencia
from apps.cashflow.liquido import liquido_da_fonte
from apps.cashflow.models import CashFlowEntry, RecurringExpense
from apps.households.models import Debt, IncomeSource, Member, TipoMembro

pytestmark = pytest.mark.django_db


def _fonte_clt(household, valor="24000.00", **extras):
    return IncomeSource.objects.create(
        household=household,
        tenant=household.tenant,
        membro=household.membros.first(),
        descricao="Salário hospital",
        tipo="clt_hospitalar",
        regime="clt",
        valor_medio_mensal=valor,
        modo_lancamento="fixa",
        **extras,
    )


class TestRetencaoNaFonte:
    def test_clt_entra_pelo_liquido(self, familia_autenticada):
        household, _, _ = familia_autenticada
        fonte = _fonte_clt(household, "24000.00")

        valor = liquido_da_fonte(fonte)

        assert valor.bruto == D("24000.00")
        assert valor.liquido < valor.bruto, "o bruto entrou sem desconto"
        assert valor.houve_retencao

    def test_a_retencao_tem_o_tamanho_esperado(self, familia_autenticada):
        """Numa renda alta, INSS e IRPF ficam perto de um quarto do bruto.

        O intervalo é largo de propósito: o teste protege a ordem de grandeza,
        não a tabela de 2025 — que muda todo ano e tem teste próprio.
        """
        household, _, _ = familia_autenticada
        valor = liquido_da_fonte(_fonte_clt(household, "24000.00"))

        proporcao = valor.retido / valor.bruto
        assert D("0.20") < proporcao < D("0.30"), f"reteve {proporcao:.1%}"

    def _dependentes(self, household, quantos):
        for i in range(quantos):
            Member.objects.create(
                household=household, tenant=household.tenant,
                nome=f"Filho {i + 1}", tipo=TipoMembro.DEPENDENTE,
            )

    def test_um_dependente_sozinho_nao_muda_o_liquido(self, familia_autenticada):
        """E está certo: o IRPF usa o desconto simplificado quando ele é maior.

        R$ 607,20 de desconto simplificado supera os R$ 189,59 de um
        dependente, então declarar por dedução seria pior. O motor escolhe o
        melhor dos dois — é o que um contador faria.
        """
        household, _, _ = familia_autenticada
        fonte = _fonte_clt(household)
        sozinho = liquido_da_fonte(fonte).liquido

        self._dependentes(household, 1)

        assert liquido_da_fonte(fonte).liquido == sozinho

    def test_a_partir_do_quarto_dependente_o_liquido_sobe(self, familia_autenticada):
        """Quatro dependentes somam R$ 758,36 e passam o simplificado."""
        household, _, _ = familia_autenticada
        fonte = _fonte_clt(household)
        sem_nenhum = liquido_da_fonte(fonte).liquido

        self._dependentes(household, 4)

        assert liquido_da_fonte(fonte).liquido > sem_nenhum

    @pytest.mark.parametrize("regime", ["pj", "autonomo"])
    def test_pj_e_autonomo_entram_pelo_valor_informado(self, familia_autenticada, regime):
        """Fora do CLT não há retenção na fonte a descontar aqui.

        No PJ a empresa fatura o valor cheio e recolhe depois, em guia
        separada — o tributo aparece como despesa própria. Descontar aqui
        cobraria duas vezes.
        """
        household, _, _ = familia_autenticada
        fonte = _fonte_clt(household, "24000.00")
        fonte.regime = regime
        fonte.save()

        valor = liquido_da_fonte(fonte)

        assert valor.liquido == D("24000.00")
        assert not valor.houve_retencao

    def test_quem_informa_o_liquido_nao_e_descontado_de_novo(self, familia_autenticada):
        """Muita gente sabe de cor o que cai na conta, não o do contrato."""
        household, _, _ = familia_autenticada
        fonte = _fonte_clt(household, "18000.00", valor_e_bruto=False)

        valor = liquido_da_fonte(fonte)

        assert valor.liquido == D("18000.00")
        assert not valor.houve_retencao

    def test_o_lancamento_do_mes_guarda_os_dois_valores(self, familia_autenticada):
        """Sem o bruto gravado, o cliente vê um número que não digitou e
        conclui que a plataforma errou a conta."""
        household, _, _ = familia_autenticada
        fonte = _fonte_clt(household, "24000.00")

        abrir_competencia(household, 2026, 8)

        lancamento = CashFlowEntry.objects.get(fonte_renda=fonte, ano=2026, mes=8)
        assert lancamento.valor_bruto == D("24000.00")
        assert lancamento.valor_realizado < D("24000.00")

    def test_sem_retencao_o_bruto_fica_vazio(self, familia_autenticada):
        """Campo preenchido sem necessidade vira ruído na tela."""
        household, _, _ = familia_autenticada
        fonte = _fonte_clt(household, "24000.00")
        fonte.regime = "pj"
        fonte.save()

        abrir_competencia(household, 2026, 8)

        lancamento = CashFlowEntry.objects.get(fonte_renda=fonte)
        assert lancamento.valor_bruto is None
        assert lancamento.valor_realizado == D("24000.00")

    def test_o_resumo_do_mes_usa_o_liquido(self, api, familia_autenticada):
        household, _, _ = familia_autenticada
        _fonte_clt(household, "24000.00")
        abrir_competencia(household, 2026, 8)

        resumo = api.get(reverse("lancamento-resumo"), {"ano": 2026, "mes": 8}).data

        assert D(resumo["receitas_realizadas"]) < D("24000.00")


class TestParcelaVirandoDespesa:
    def _cadastrar_divida(self, api, **extras):
        corpo = {
            "tipo": "financiamento_imovel",
            "descricao": "Financiamento do apartamento",
            "saldo_devedor": "600000",
            "taxa_juros_mensal": "0.85",
            "parcelas_restantes": 240,
            "valor_parcela": "6200",
            **extras,
        }
        return api.post(reverse("divida-list"), corpo, format="json")

    def test_cadastrar_divida_cria_a_despesa_da_parcela(self, api, familia_autenticada):
        household, _, _ = familia_autenticada

        resposta = self._cadastrar_divida(api)
        assert resposta.status_code == 201

        despesa = RecurringExpense.objects.get(household=household)
        assert despesa.valor_previsto == D("6200")
        assert despesa.categoria == "divida"
        assert despesa.descricao == "Financiamento do apartamento"

    def test_a_parcela_aparece_no_fluxo_de_caixa(self, api, familia_autenticada):
        """O sintoma que o cliente via: cadastrou e não achou em lugar nenhum."""
        household, _, _ = familia_autenticada
        self._cadastrar_divida(api)

        abrir_competencia(household, 2026, 8)

        lancamentos = CashFlowEntry.objects.filter(household=household, tipo="despesa")
        assert any(item.valor_realizado == D("6200") for item in lancamentos)

    def test_a_vigencia_acaba_com_a_ultima_parcela(self, api, familia_autenticada):
        """Financiamento tem fim. Sem isso, a parcela de um carro já quitado
        continuaria saindo do orçamento por anos."""
        household, _, _ = familia_autenticada
        self._cadastrar_divida(api, parcelas_restantes=12,
                               data_primeira_parcela="2026-01-01")

        despesa = RecurringExpense.objects.get(household=household)
        assert despesa.vigencia_inicio == date(2026, 1, 1)
        assert despesa.vigencia_fim == date(2026, 12, 1)

    def test_divida_sem_prazo_fica_com_vigencia_aberta(self, api, familia_autenticada):
        """Cheque especial e rotativo não têm data para acabar."""
        household, _, _ = familia_autenticada
        self._cadastrar_divida(api, parcelas_restantes=0)

        assert RecurringExpense.objects.get(household=household).vigencia_fim is None

    def test_editar_a_parcela_move_a_despesa(self, api, familia_autenticada):
        household, _, _ = familia_autenticada
        divida_id = self._cadastrar_divida(api).data["id"]

        api.patch(
            reverse("divida-detail", args=[divida_id]),
            {"valor_parcela": "5800"},
            format="json",
        )

        assert RecurringExpense.objects.get(household=household).valor_previsto == D("5800")

    def test_nao_duplica_ao_editar_varias_vezes(self, api, familia_autenticada):
        household, _, _ = familia_autenticada
        divida_id = self._cadastrar_divida(api).data["id"]

        for valor in ("5800", "5900", "6000"):
            api.patch(
                reverse("divida-detail", args=[divida_id]),
                {"valor_parcela": valor},
                format="json",
            )

        assert RecurringExpense.objects.filter(household=household).count() == 1

    def test_divida_sem_parcela_informada_nao_cria_despesa(self, api, familia_autenticada):
        """Parcela de valor zero no orçamento é ruído."""
        household, _, _ = familia_autenticada
        self._cadastrar_divida(api, valor_parcela="0")

        assert not RecurringExpense.objects.filter(household=household).exists()

    def test_apagar_a_divida_tira_a_parcela_do_orcamento(self, api, familia_autenticada):
        """O vínculo é SET_NULL: sem apagar explicitamente, a despesa
        sobreviveria órfã, descontando todo mês sem origem visível."""
        household, _, _ = familia_autenticada
        divida_id = self._cadastrar_divida(api).data["id"]

        api.delete(reverse("divida-detail", args=[divida_id]))

        assert not RecurringExpense.objects.filter(household=household).exists()
        assert not Debt.objects.filter(household=household).exists()


class TestValorBrutoNaoEEditavel:
    """`valor_bruto` é calculado pelo servidor, nunca aceito do cliente.

    Sem isso, alguém editando um lançamento poderia declarar um "bruto"
    qualquer, sem relação com o que a retenção de fato descontou.
    """

    def test_enviar_valor_bruto_na_edicao_e_ignorado(self, api, familia_autenticada):
        household, _, _ = familia_autenticada
        fonte = _fonte_clt(household, "24000.00")
        abrir_competencia(household, 2026, 8)
        lancamento = CashFlowEntry.objects.get(fonte_renda=fonte)

        api.patch(
            reverse("lancamento-detail", args=[lancamento.id]),
            {"valor_bruto": "999999.00"},
            format="json",
        )

        lancamento.refresh_from_db()
        assert lancamento.valor_bruto == D("24000.00"), "valor forjado não deveria ter entrado"


class TestPreviaDeLiquidoClt:
    """A prévia que a tela mostra enquanto a pessoa ainda está digitando.

    Precisa da mesma regra da materialização real — e precisa responder sem
    exigir que nenhuma fonte de renda exista ainda, porque é chamada antes de
    qualquer coisa ser salva.
    """

    def test_exige_autenticacao(self, api):
        api.logout()
        resposta = api.get(reverse("simulador-liquido-clt"), {"valor_bruto": "24000"})
        assert resposta.status_code == 401

    def test_calcula_sem_nenhuma_fonte_cadastrada(self, api, familia_autenticada):
        resposta = api.get(reverse("simulador-liquido-clt"), {"valor_bruto": "24000"})

        assert resposta.status_code == 200
        assert D(resposta.data["bruto"]) == D("24000.00")
        assert D(resposta.data["liquido"]) < D("24000.00")
        assert D(resposta.data["retido"]) > 0

    def test_bate_com_o_que_a_materializacao_de_fato_grava(self, api, familia_autenticada):
        """A prévia não pode dizer um número e o lançamento gravar outro."""
        household, _, _ = familia_autenticada
        api.post(
            reverse("fonte-renda-list"),
            {
                "membro": str(household.membros.first().id),
                "descricao": "Salário hospital",
                "tipo": "clt_hospitalar",
                "regime": "clt",
                "valor_medio_mensal": "24000.00",
                "modo_lancamento": "fixa",
            },
            format="json",
        )
        abrir_competencia(household, 2026, 8)
        lancamento = CashFlowEntry.objects.get(household=household, ano=2026, mes=8)

        previa = api.get(reverse("simulador-liquido-clt"), {"valor_bruto": "24000"}).data

        assert D(previa["liquido"]) == lancamento.valor_realizado

    def test_dependentes_do_nucleo_entram_na_conta(self, api, familia_autenticada):
        household, _, _ = familia_autenticada
        sem_dependente = api.get(
            reverse("simulador-liquido-clt"), {"valor_bruto": "24000"}
        ).data

        Member.objects.create(household=household, tenant=household.tenant, nome="Filho 1", tipo="dependente")
        Member.objects.create(household=household, tenant=household.tenant, nome="Filho 2", tipo="dependente")
        Member.objects.create(household=household, tenant=household.tenant, nome="Filho 3", tipo="dependente")
        Member.objects.create(household=household, tenant=household.tenant, nome="Filho 4", tipo="dependente")

        com_quatro = api.get(reverse("simulador-liquido-clt"), {"valor_bruto": "24000"}).data

        assert D(com_quatro["liquido"]) > D(sem_dependente["liquido"])

    def test_valor_zero_ou_negativo_nao_gera_erro(self, api, familia_autenticada):
        resposta = api.get(reverse("simulador-liquido-clt"), {"valor_bruto": "0"})
        assert resposta.status_code == 200
        assert D(resposta.data["liquido"]) == D("0.00")

    def test_sem_o_parametro_e_erro_de_validacao_claro(self, api, familia_autenticada):
        resposta = api.get(reverse("simulador-liquido-clt"))
        assert resposta.status_code == 400
        assert "valor_bruto" in resposta.data
