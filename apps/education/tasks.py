"""Job mensal do relatório educacional (seção 3.6)."""

import logging
from datetime import date

from celery import shared_task

from .ai import MESES, gerar_conteudo
from .bcb import coletar_indicadores
from .models import EducationalReport, StatusRelatorio

logger = logging.getLogger(__name__)


def _mes_anterior(hoje: date) -> tuple[int, int]:
    return (hoje.year - 1, 12) if hoje.month == 1 else (hoje.year, hoje.month - 1)


@shared_task(bind=True, max_retries=3, default_retry_delay=60 * 30)
def gerar_relatorio_mensal(self, ano: int | None = None, mes: int | None = None):
    """Coleta indicadores oficiais, gera o texto e grava como RASCUNHO.

    Nunca publica automaticamente: a revisão humana é parte do controle de
    compliance do módulo.
    """
    if ano is None or mes is None:
        ano, mes = _mes_anterior(date.today())

    if EducationalReport.objects.filter(tenant=None, ano=ano, mes=mes).exists():
        logger.info("Relatório de %02d/%d já existe — nada a fazer.", mes, ano)
        return None

    try:
        indicadores = coletar_indicadores(ano, mes)
    except Exception as exc:  # rede/BCB fora do ar
        logger.warning("Falha ao coletar indicadores do BCB: %s", exc)
        raise self.retry(exc=exc) from exc

    if not indicadores.completo:
        # IPCA do mês costuma sair até o dia 10 — tenta de novo mais tarde.
        logger.info("Indicadores de %02d/%d ainda incompletos.", mes, ano)
        raise self.retry(countdown=60 * 60 * 24)

    conteudo = gerar_conteudo(indicadores)

    from django.conf import settings

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
    logger.info("Relatório %s criado como rascunho.", relatorio.id)
    return str(relatorio.id)
