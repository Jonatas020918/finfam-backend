"""Consolidação do fluxo de caixa (seção 3.2)."""

from decimal import Decimal

from django.db.models import Sum

from .models import CashFlowEntry, TipoLancamento

ZERO = Decimal("0.00")


def _soma(qs, campo) -> Decimal:
    return qs.aggregate(total=Sum(campo))["total"] or ZERO


def resumo_mensal(household, ano: int, mes: int) -> dict:
    """Consolidado do mês: total da família, por categoria e por membro.

    A visão padrão é a da família; a quebra por membro mostra quanto cada um
    contribui e gasta, sem esconder o consolidado.
    """
    lancamentos = CashFlowEntry.objects.filter(household=household, ano=ano, mes=mes)
    receitas = lancamentos.filter(tipo=TipoLancamento.RECEITA)
    despesas = lancamentos.filter(tipo=TipoLancamento.DESPESA)

    receitas_realizadas = _soma(receitas, "valor_realizado")
    despesas_realizadas = _soma(despesas, "valor_realizado")
    saldo = receitas_realizadas - despesas_realizadas

    por_categoria = {
        linha["categoria"]: linha["total"]
        for linha in lancamentos.values("categoria").annotate(total=Sum("valor_realizado"))
    }

    por_membro = []
    for membro in household.membros.all():
        r = _soma(receitas.filter(membro=membro), "valor_realizado")
        d = _soma(despesas.filter(membro=membro), "valor_realizado")
        if r or d:
            por_membro.append(
                {
                    "membro_id": str(membro.id),
                    "membro_nome": membro.nome,
                    "receitas": r,
                    "despesas": d,
                    "saldo": r - d,
                }
            )

    r_comp = _soma(receitas.filter(membro__isnull=True), "valor_realizado")
    d_comp = _soma(despesas.filter(membro__isnull=True), "valor_realizado")
    if r_comp or d_comp:
        por_membro.append(
            {
                "membro_id": None,
                "membro_nome": "Compartilhado (família)",
                "receitas": r_comp,
                "despesas": d_comp,
                "saldo": r_comp - d_comp,
            }
        )

    taxa_poupanca = (saldo / receitas_realizadas * 100) if receitas_realizadas else ZERO

    return {
        "ano": ano,
        "mes": mes,
        "receitas_realizadas": receitas_realizadas,
        "despesas_realizadas": despesas_realizadas,
        "saldo_realizado": saldo,
        "receitas_orcadas": _soma(receitas, "valor_orcado"),
        "despesas_orcadas": _soma(despesas, "valor_orcado"),
        "saldo_orcado": _soma(receitas, "valor_orcado") - _soma(despesas, "valor_orcado"),
        "taxa_poupanca": taxa_poupanca.quantize(Decimal("0.01")),
        "por_categoria": por_categoria,
        "por_membro": por_membro,
    }
