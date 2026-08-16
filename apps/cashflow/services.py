"""Consolidação do fluxo de caixa (seção 3.2)."""

from decimal import Decimal

from django.db.models import Sum

from apps.households.models import RegimeTributario

from .models import CashFlowEntry, TipoLancamento

ZERO = Decimal("0.00")


def _soma(qs, campo) -> Decimal:
    return qs.aggregate(total=Sum(campo))["total"] or ZERO


def _quebra_de_receitas(receitas, total: Decimal) -> dict:
    """Receitas do mês por regime tributário e por fonte declarada.

    É o que permite ao simulador partir do que a pessoa realmente recebeu, em
    vez de pedir que ela redigite o valor. Receita sem regime aparece à parte —
    o número existe, mas não pode alimentar cálculo tributário.
    """
    por_regime = []
    for regime, rotulo in RegimeTributario.choices:
        valor = _soma(receitas.filter(regime=regime), "valor_realizado")
        if not valor:
            continue
        participacao = (valor / total * 100) if total else ZERO
        por_regime.append(
            {
                "regime": regime,
                "rotulo": rotulo,
                "receitas": valor,
                "participacao_percentual": participacao.quantize(Decimal("0.01")),
            }
        )

    por_fonte = []
    agrupado = (
        receitas.values(
            "fonte_renda_id",
            "fonte_renda__descricao",
            "fonte_renda__membro__nome",
            "regime",
            "tipo_renda",
        )
        .annotate(total=Sum("valor_realizado"))
        .order_by("-total")
    )
    for linha in agrupado:
        por_fonte.append(
            {
                "fonte_id": str(linha["fonte_renda_id"]) if linha["fonte_renda_id"] else None,
                "descricao": linha["fonte_renda__descricao"] or "Sem fonte vinculada",
                "membro_nome": linha["fonte_renda__membro__nome"],
                "regime": linha["regime"] or "",
                "tipo_renda": linha["tipo_renda"] or "",
                "receitas": linha["total"] or ZERO,
            }
        )

    return {
        "por_regime": por_regime,
        "por_fonte": por_fonte,
        "receitas_nao_classificadas": _soma(receitas.filter(regime=""), "valor_realizado"),
    }


def base_para_simulacao(household, ano: int, mes: int) -> dict:
    """Renda realizada no mês, pronta para alimentar o simulador PJ x CLT.

    Devolve o bruto por membro e a quebra por regime, para que a tela consiga
    pré-preencher a simulação de cada um — inclusive quando o casal está em
    regimes diferentes, que é o caso comum (seção 3.3).
    """
    receitas = CashFlowEntry.objects.filter(
        household=household, ano=ano, mes=mes, tipo=TipoLancamento.RECEITA
    )

    por_membro = []
    for membro in household.membros.all():
        do_membro = receitas.filter(membro=membro)
        bruto = _soma(do_membro, "valor_realizado")
        if not bruto:
            continue

        regimes = {}
        for regime, _rotulo in RegimeTributario.choices:
            valor = _soma(do_membro.filter(regime=regime), "valor_realizado")
            if valor:
                regimes[regime] = valor

        predominante = max(regimes, key=regimes.get) if regimes else None
        por_membro.append(
            {
                "membro_id": str(membro.id),
                "membro_nome": membro.nome,
                "receita_bruta_mensal": bruto,
                "por_regime": regimes,
                "regime_predominante": predominante,
                "classificada": _soma(
                    do_membro.exclude(regime=""), "valor_realizado"
                ),
                "fontes": [
                    {
                        "fonte_id": str(linha["fonte_renda_id"]) if linha["fonte_renda_id"] else None,
                        "descricao": linha["fonte_renda__descricao"] or "Sem fonte vinculada",
                        "regime": linha["regime"] or "",
                        "receitas": linha["total"] or ZERO,
                    }
                    for linha in do_membro.values(
                        "fonte_renda_id", "fonte_renda__descricao", "regime"
                    ).annotate(total=Sum("valor_realizado"))
                ],
            }
        )

    return {
        "referencia": {"ano": ano, "mes": mes},
        "total_familia": _soma(receitas, "valor_realizado"),
        "compartilhado": _soma(receitas.filter(membro__isnull=True), "valor_realizado"),
        "por_membro": por_membro,
    }


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
        **_quebra_de_receitas(receitas, receitas_realizadas),
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
