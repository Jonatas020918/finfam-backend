"""Gera o relatório educacional de um mês sem depender de Celery/Redis.

Serve para desenvolvimento e para reprocessar um mês específico em produção.
Em operação normal quem dispara é o Celery Beat (config/celery.py).

    python manage.py gerar_relatorio_educacional
    python manage.py gerar_relatorio_educacional --ano 2026 --mes 7
    python manage.py gerar_relatorio_educacional --so-indicadores
"""

from datetime import date

from anthropic import APIStatusError
from django.core.management.base import BaseCommand, CommandError

from apps.education.ai import MESES, gerar_conteudo
from apps.education.bcb import coletar_indicadores
from apps.education.models import EducationalReport, StatusRelatorio


class Command(BaseCommand):
    help = "Coleta Selic/IPCA no Banco Central e gera o relatório educacional do mês."

    def add_arguments(self, parser):
        parser.add_argument("--ano", type=int, help="Padrão: mês anterior ao atual.")
        parser.add_argument("--mes", type=int)
        parser.add_argument(
            "--so-indicadores",
            action="store_true",
            help="Só consulta o Banco Central e imprime os números, sem chamar a IA.",
        )
        parser.add_argument(
            "--refazer",
            action="store_true",
            help="Substitui o relatório do mês, se já existir.",
        )
        parser.add_argument(
            "--exemplo",
            action="store_true",
            help=(
                "Cria o relatório com os indicadores reais do BCB e um texto de exemplo, "
                "sem chamar a IA. Só para desenvolvimento — nunca publique este conteúdo."
            ),
        )

    def handle(self, *args, **opcoes):
        ano, mes = opcoes.get("ano"), opcoes.get("mes")
        if ano is None or mes is None:
            hoje = date.today()
            ano, mes = (hoje.year - 1, 12) if hoje.month == 1 else (hoje.year, hoje.month - 1)
        if not 1 <= mes <= 12:
            raise CommandError("Mês deve estar entre 1 e 12.")

        existente = EducationalReport.objects.filter(tenant=None, ano=ano, mes=mes).first()
        if existente and not opcoes["refazer"]:
            raise CommandError(
                f"Já existe relatório para {mes:02d}/{ano} ({existente.get_status_display()}). "
                "Use --refazer para substituir."
            )

        self.stdout.write(f"Consultando o Banco Central para {mes:02d}/{ano}...")
        indicadores = coletar_indicadores(ano, mes)
        self.stdout.write(
            f"  Selic meta: {indicadores.selic_meta}% a.a. "
            f"(variação no mês: {indicadores.selic_variacao_mes} p.p.)\n"
            f"  IPCA do mês: {indicadores.ipca_mes}% | 12 meses: {indicadores.ipca_12m}%"
        )

        if not indicadores.completo:
            raise CommandError(
                "Indicadores incompletos — o IPCA do mês costuma sair até o dia 10. "
                "Tente novamente mais tarde."
            )

        if opcoes["so_indicadores"]:
            return

        if opcoes["exemplo"]:
            self.stdout.write(self.style.WARNING("Montando conteúdo de EXEMPLO (a IA não é chamada)."))
            conteudo = conteudo_de_exemplo(indicadores)
        else:
            self.stdout.write("Gerando o texto com a IA (dados oficiais como única fonte)...")
            try:
                conteudo = gerar_conteudo(indicadores)
            except RuntimeError as erro:
                raise CommandError(str(erro)) from erro
            except APIStatusError as erro:
                raise CommandError(self._mensagem_api(erro)) from erro

        from django.conf import settings

        if existente:
            existente.delete()

        relatorio = EducationalReport.objects.create(
            tenant=None,
            ano=ano,
            mes=mes,
            titulo=conteudo.get("titulo") or f"Panorama de {MESES[mes - 1]} de {ano}",
            selic_meta_percentual=indicadores.selic_meta,
            selic_variacao_mes=indicadores.selic_variacao_mes,
            ipca_mes_percentual=indicadores.ipca_mes,
            ipca_12m_percentual=indicadores.ipca_12m,
            secoes=conteudo.get("secoes", []),
            glossario=conteudo.get("glossario", []),
            status=StatusRelatorio.RASCUNHO,
            modelo_ia=settings.ANTHROPIC_MODEL,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f'Rascunho criado: "{relatorio.titulo}" '
                f"({len(relatorio.secoes)} seções, {len(relatorio.glossario)} termos no glossário)."
            )
        )
        self.stdout.write(
            "O relatório NÃO é publicado automaticamente. Revise em /admin/ e use a ação "
            '"Publicar relatórios revisados" — a revisão humana é exigência de compliance.'
        )

    def _mensagem_api(self, erro: "APIStatusError") -> str:
        """Traduz os erros mais comuns da API para algo acionável no terminal."""
        detalhe = getattr(erro, "message", str(erro))
        if erro.status_code == 401:
            return f"Chave da Anthropic inválida ou revogada ({detalhe})."
        if erro.status_code == 400 and "credit balance" in str(detalhe):
            return (
                "A conta da Anthropic está sem créditos. Adicione saldo em "
                "console.anthropic.com (Plans & Billing) ou rode com --exemplo para "
                "criar um rascunho de desenvolvimento sem chamar a IA."
            )
        if erro.status_code == 429:
            return "Limite de requisições atingido na API da Anthropic. Tente de novo em instantes."
        return f"A API da Anthropic recusou a requisição ({erro.status_code}): {detalhe}"


def conteudo_de_exemplo(ind) -> dict:
    """Texto de desenvolvimento com os indicadores reais do mês.

    Existe para destravar o trabalho no frontend sem consumir a API. É marcado
    explicitamente como exemplo justamente para não ser publicado por engano.
    """
    return {
        "titulo": f"[EXEMPLO] Panorama de {MESES[ind.mes - 1]} de {ind.ano}",
        "secoes": [
            {
                "titulo": "Panorama macroeconômico",
                "corpo": (
                    f"Conteúdo de exemplo para desenvolvimento — não publique. "
                    f"A meta Selic encerrou o mês em {ind.selic_meta}% ao ano, com variação de "
                    f"{ind.selic_variacao_mes} ponto percentual no período. O IPCA do mês foi de "
                    f"{ind.ipca_mes}%, acumulando {ind.ipca_12m}% em doze meses. "
                    "Na prática, a Selic é o juro de referência da economia: quando ela está alta, "
                    "aplicações que acompanham os juros rendem mais, e crédito fica mais caro."
                ),
            },
            {
                "titulo": "O que isso significa na prática",
                "corpo": (
                    "Conteúdo de exemplo para desenvolvimento — não publique. Com juros nesse "
                    "patamar, o custo de carregar dívidas (financiamento de consultório, "
                    "equipamentos, cartão) pesa mais no orçamento do que em períodos de juro baixo."
                ),
            },
        ],
        "glossario": [
            {
                "termo": "Selic",
                "definicao": "Taxa básica de juros da economia, definida pelo Copom a cada 45 dias.",
            },
            {
                "termo": "IPCA",
                "definicao": "Índice oficial de inflação do Brasil, medido pelo IBGE.",
            },
        ],
    }
