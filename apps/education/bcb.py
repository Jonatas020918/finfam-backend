"""Cliente da API pública do Banco Central (SGS).

Os indicadores do relatório educacional vêm sempre daqui — nunca de estimativa
gerada por IA (seção 3.6). Séries usadas:

  432  — Meta Selic definida pelo Copom (% a.a., diária)
  433  — IPCA, variação mensal (%)
  13522 — IPCA acumulado em 12 meses (%)
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import httpx
from django.conf import settings

SERIE_SELIC_META = 432
SERIE_IPCA_MENSAL = 433
SERIE_IPCA_12M = 13522


@dataclass
class IndicadoresMes:
    ano: int
    mes: int
    selic_meta: Decimal | None
    selic_variacao_mes: Decimal | None
    ipca_mes: Decimal | None
    ipca_12m: Decimal | None

    @property
    def completo(self) -> bool:
        return self.selic_meta is not None and self.ipca_mes is not None


def _url(serie: int) -> str:
    return f"{settings.BCB_API_BASE_URL}.{serie}/dados"


def _buscar_serie(serie: int, inicio: date, fim: date, timeout: float = 15.0) -> list[dict]:
    params = {
        "formato": "json",
        "dataInicial": inicio.strftime("%d/%m/%Y"),
        "dataFinal": fim.strftime("%d/%m/%Y"),
    }
    resposta = httpx.get(_url(serie), params=params, timeout=timeout)
    resposta.raise_for_status()
    return resposta.json()


def _ultimo_valor(dados: list[dict]) -> Decimal | None:
    if not dados:
        return None
    return Decimal(str(dados[-1]["valor"]))


def _primeiro_valor(dados: list[dict]) -> Decimal | None:
    if not dados:
        return None
    return Decimal(str(dados[0]["valor"]))


def coletar_indicadores(ano: int, mes: int) -> IndicadoresMes:
    """Coleta os indicadores do mês de referência.

    Falha de rede não é tratada aqui: a task Celery decide o retry, e um
    relatório sem dado oficial não deve ser gerado.
    """
    inicio = date(ano, mes, 1)
    fim = date(ano + (mes // 12), (mes % 12) + 1, 1)

    selic = _buscar_serie(SERIE_SELIC_META, inicio, fim)
    ipca_mes = _buscar_serie(SERIE_IPCA_MENSAL, inicio, fim)
    ipca_12m = _buscar_serie(SERIE_IPCA_12M, inicio, fim)

    selic_inicio = _primeiro_valor(selic)
    selic_fim = _ultimo_valor(selic)
    variacao = (
        selic_fim - selic_inicio if selic_inicio is not None and selic_fim is not None else None
    )

    return IndicadoresMes(
        ano=ano,
        mes=mes,
        selic_meta=selic_fim,
        selic_variacao_mes=variacao,
        ipca_mes=_ultimo_valor(ipca_mes),
        ipca_12m=_ultimo_valor(ipca_12m),
    )
