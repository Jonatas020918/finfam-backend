"""Sincronização dos indicadores oficiais do Banco Central."""

import logging
from datetime import date

from .bcb import coletar_indicadores
from .models import IndicadorMensal

logger = logging.getLogger(__name__)


def _competencias_recentes(referencia: date, meses: int) -> list[tuple[int, int]]:
    """Últimas N competências, da mais antiga para a mais recente."""
    competencias = []
    ano, mes = referencia.year, referencia.month
    for _ in range(meses):
        competencias.append((ano, mes))
        mes -= 1
        if mes == 0:
            mes = 12
            ano -= 1
    return list(reversed(competencias))


def sincronizar_indicadores(meses: int = 3, referencia: date | None = None) -> list[IndicadorMensal]:
    """Busca e grava os indicadores das últimas competências.

    Revisita meses já gravados de propósito: o IPCA de um mês só é publicado por
    volta do dia 10 do mês seguinte, e o IBGE eventualmente revisa números. Uma
    janela curta mantém tudo em dia sem varrer a série inteira todo dia.

    Falha de rede em uma competência não interrompe as demais — é melhor ter
    dois meses atualizados de três do que abortar tudo.
    """
    referencia = referencia or date.today()
    atualizados = []

    for ano, mes in _competencias_recentes(referencia, meses):
        try:
            dados = coletar_indicadores(ano, mes)
        except Exception as erro:  # rede, timeout, BCB fora do ar
            logger.warning("Falha ao coletar %02d/%d no BCB: %s", mes, ano, erro)
            continue

        # Só grava o que veio preenchido: uma série indisponível na consulta de
        # hoje não pode apagar o valor que já estava salvo de ontem.
        campos = {
            "selic_meta_percentual": dados.selic_meta,
            "selic_variacao_mes": dados.selic_variacao_mes,
            "ipca_mes_percentual": dados.ipca_mes,
            "ipca_12m_percentual": dados.ipca_12m,
        }
        defaults = {campo: valor for campo, valor in campos.items() if valor is not None}

        indicador, _ = IndicadorMensal.objects.update_or_create(
            ano=ano, mes=mes, defaults=defaults
        )
        atualizados.append(indicador)

    return atualizados
