"""Cria a despesa fixa das dívidas que foram cadastradas antes dessa ligação existir.

A sincronização entre dívida e parcela roda automaticamente desde que o
DebtViewSet passou a chamar `sincronizar_despesa` em cada criação e edição.
Toda dívida cadastrada **antes** dessa mudança ficou sem a despesa
correspondente — o saldo devedor está lá, a parcela nunca virou desconto no
orçamento.

Rodar uma vez por ambiente resolve o passivo:

    python manage.py sincronizar_parcelas
    python manage.py sincronizar_parcelas --aplicar   # sem --aplicar, só mostra
"""

from datetime import date

from django.core.management.base import BaseCommand

from apps.cashflow.competencia import abrir_competencia
from apps.cashflow.models import RecurringExpense
from apps.cashflow.parcelas import sincronizar_despesa
from apps.households.models import Debt


class Command(BaseCommand):
    help = "Cria a despesa fixa de dívidas cadastradas antes da sincronização existir."

    def add_arguments(self, parser):
        parser.add_argument(
            "--aplicar",
            action="store_true",
            help="Sem esta flag, o comando só lista o que faria — nada é gravado.",
        )

    def handle(self, *args, **opcoes):
        aplicar = opcoes["aplicar"]
        pendentes = [
            divida
            for divida in Debt.objects.select_related("household").all()
            if not RecurringExpense.objects.filter(divida=divida).exists()
        ]

        if not pendentes:
            self.stdout.write(self.style.SUCCESS("Nenhuma dívida pendente de sincronização."))
            return

        self.stdout.write(f"{len(pendentes)} dívida(s) sem despesa correspondente:\n")
        for divida in pendentes:
            self.stdout.write(
                f"  {divida.household.nome:.<30} {divida.descricao:.<25} "
                f"parcela R$ {divida.valor_parcela}"
            )

        if not aplicar:
            self.stdout.write(
                self.style.WARNING("\nModo de simulação. Rode com --aplicar para gravar.")
            )
            return

        criadas = 0
        households_afetados = set()
        for divida in pendentes:
            if sincronizar_despesa(divida) is not None:
                criadas += 1
                households_afetados.add(divida.household)

        self.stdout.write(self.style.SUCCESS(f"\n{criadas} despesa(s) criada(s)."))

        # Sem isto, quem já tinha o mês corrente aberto só veria a parcela a
        # partir do mês que vem — a materialização é get_or_create, então
        # reabrir a mesma competência é seguro: só preenche o que faltava.
        hoje = date.today()
        for household in households_afetados:
            abrir_competencia(household, hoje.year, hoje.month)
        self.stdout.write(
            self.style.SUCCESS(
                f"Mês corrente ({hoje.month:02d}/{hoje.year}) materializado para "
                f"{len(households_afetados)} núcleo(s) familiar(es)."
            )
        )
