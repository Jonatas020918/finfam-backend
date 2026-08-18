"""Sincroniza Selic e IPCA sem depender de Celery/Redis.

Em produção quem dispara é o Celery Beat, diariamente. Este comando serve para
desenvolvimento, para a primeira carga e para forçar uma atualização quando o
BCB publica um índice fora da cadência esperada.

    python manage.py atualizar_indicadores
    python manage.py atualizar_indicadores --meses 12
"""

from django.core.management.base import BaseCommand, CommandError

from apps.education.services import sincronizar_indicadores


class Command(BaseCommand):
    help = "Busca Selic e IPCA no Banco Central e grava os indicadores por competência."

    def add_arguments(self, parser):
        parser.add_argument(
            "--meses",
            type=int,
            default=3,
            help="Quantas competências revisitar, contando a partir do mês atual (padrão: 3).",
        )

    def handle(self, *args, **opcoes):
        meses = opcoes["meses"]
        if meses < 1:
            raise CommandError("--meses deve ser pelo menos 1.")

        self.stdout.write(f"Consultando o Banco Central ({meses} competências)...")
        atualizados = sincronizar_indicadores(meses=meses)

        if not atualizados:
            raise CommandError(
                "Nenhuma competência sincronizada. Verifique a conexão com api.bcb.gov.br."
            )

        for indicador in atualizados:
            estado = "completo" if indicador.completo else "aguardando IPCA"
            self.stdout.write(
                f"  {indicador.mes:02d}/{indicador.ano} — "
                f"Selic {indicador.selic_meta_percentual}% a.a. · "
                f"IPCA {indicador.ipca_mes_percentual}% no mês · "
                f"{indicador.ipca_12m_percentual}% em 12m ({estado})"
            )

        self.stdout.write(
            self.style.SUCCESS(f"{len(atualizados)} competência(s) sincronizada(s).")
        )
