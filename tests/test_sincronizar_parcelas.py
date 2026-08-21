"""O comando que resolve o passivo de dívidas cadastradas antes da sincronização.

Toda dívida criada antes de DebtViewSet.perform_create chamar
sincronizar_despesa ficou sem a despesa fixa correspondente — o saldo devedor
está lá, a parcela nunca desconta o orçamento. Este comando é o reparo, e
precisa provar duas coisas: que ele cria a despesa que faltava, e que ela
aparece no fluxo de caixa do mês corrente sem exigir que o cliente reabra nada
manualmente.
"""

from datetime import date
from decimal import Decimal as D
from io import StringIO

import pytest
from django.core.management import call_command

from apps.cashflow.competencia import abrir_competencia
from apps.cashflow.models import CashFlowEntry, RecurringExpense
from apps.households.models import Debt

pytestmark = pytest.mark.django_db


def _divida_orfa(household, **extras):
    """Simula uma dívida como as criadas antes da correção: sem despesa."""
    return Debt.objects.create(
        household=household,
        tenant=household.tenant,
        membro=household.membros.first(),
        tipo="financiamento_imovel",
        descricao="Apartamento",
        saldo_devedor="600000",
        valor_parcela="4200",
        parcelas_restantes=200,
        **extras,
    )


class TestSincronizarParcelas:
    def test_sem_aplicar_nao_grava_nada(self, familia_autenticada):
        household, _, _ = familia_autenticada
        _divida_orfa(household)

        call_command("sincronizar_parcelas", stdout=StringIO())

        assert not RecurringExpense.objects.filter(household=household).exists()

    def test_com_aplicar_cria_a_despesa(self, familia_autenticada):
        household, _, _ = familia_autenticada
        divida = _divida_orfa(household)

        call_command("sincronizar_parcelas", "--aplicar", stdout=StringIO())

        despesa = RecurringExpense.objects.get(divida=divida)
        assert despesa.valor_previsto == D("4200")

    def test_a_parcela_aparece_no_mes_corrente_mesmo_ja_aberto(self, familia_autenticada):
        """O caso real: o cliente já usa a plataforma, o mês já foi aberto, e
        a dívida antiga nunca apareceu ali."""
        household, _, _ = familia_autenticada
        hoje = date.today()
        abrir_competencia(household, hoje.year, hoje.month)  # já aberto, sem a dívida
        _divida_orfa(household)

        call_command("sincronizar_parcelas", "--aplicar", stdout=StringIO())

        lancamentos = CashFlowEntry.objects.filter(
            household=household, ano=hoje.year, mes=hoje.month, tipo="despesa"
        )
        assert any(item.valor_realizado == D("4200") for item in lancamentos)

    def test_nao_duplica_quem_ja_esta_sincronizado(self, familia_autenticada):
        """Dívida cadastrada depois da correção não deve ser tocada de novo."""
        household, _, _ = familia_autenticada
        divida = _divida_orfa(household)
        divida.refresh_from_db()  # valor_parcela chega como Decimal, não str
        from apps.cashflow.parcelas import sincronizar_despesa

        sincronizar_despesa(divida)  # já sincronizada, como uma dívida nova

        call_command("sincronizar_parcelas", "--aplicar", stdout=StringIO())

        assert RecurringExpense.objects.filter(household=household).count() == 1

    def test_relatorio_lista_o_que_encontrou(self, familia_autenticada):
        household, _, _ = familia_autenticada
        _divida_orfa(household)

        saida = StringIO()
        call_command("sincronizar_parcelas", stdout=saida)

        assert "Apartamento" in saida.getvalue()
        assert "1 dívida" in saida.getvalue()

    def test_sem_pendencias_nao_faz_nada(self, familia_autenticada):
        saida = StringIO()
        call_command("sincronizar_parcelas", "--aplicar", stdout=saida)

        assert "Nenhuma dívida pendente" in saida.getvalue()
