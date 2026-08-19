"""Rotinas agendadas da assinatura."""

import logging

from celery import shared_task

from .gateways import encerrar_periodos_vencidos

logger = logging.getLogger(__name__)


@shared_task(name="apps.billing.tasks.encerrar_periodos")
def encerrar_periodos() -> dict[str, int]:
    """Fecha diariamente os testes e as carências que venceram.

    O acesso em si não depende desta tarefa — `da_acesso` compara as datas na
    hora, então ninguém entra a mais por ela não ter rodado. O que depende é o
    `status` gravado: sem isso, uma base inteira fica marcada como "em teste"
    para sempre, e qualquer leitura de quantos clientes existem de verdade sai
    errada.
    """
    resultado = encerrar_periodos_vencidos()
    if resultado["trials_encerrados"] or resultado["carencias_encerradas"]:
        logger.info(
            "Assinaturas encerradas: %s testes, %s carências.",
            resultado["trials_encerrados"],
            resultado["carencias_encerradas"],
        )
    return resultado
