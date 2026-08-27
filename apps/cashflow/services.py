"""Consolidação do fluxo de caixa (seção 3.2)."""

from datetime import date
from decimal import Decimal

from django.db.models import Sum

from apps.households.models import RegimeTributario

from .models import CashFlowEntry, RecurringExpense, TipoLancamento

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


def historico_consolidado(household, ate_ano: int, ate_mes: int, meses: int = 12) -> dict:
    """Vários meses de fluxo de caixa numa leitura só.

    A plataforma inteira é mensal, e as decisões que ela promete apoiar não
    são: trocar de regime, antecipar financiamento e definir quanto guardar
    se decidem olhando o ano. Quem tem renda variável precisa ver o mês fraco
    ao lado do forte — é a diferença entre "ganho bem" e "ganho bem na média,
    e em janeiro faltou".

    Devolve mês a mês e o consolidado do período, incluindo o melhor e o pior
    mês, que são justamente os que a média esconde.
    """
    meses = max(1, min(meses, 36))
    competencias = []
    fim = ate_ano * 12 + (ate_mes - 1)

    for passo in range(meses - 1, -1, -1):
        indice = fim - passo
        competencias.append((indice // 12, indice % 12 + 1))

    linhas = []
    por_categoria: dict[str, Decimal] = {}
    total_receitas = ZERO
    total_despesas = ZERO

    for ano, mes in competencias:
        resumo = resumo_mensal(household, ano, mes)
        total_receitas += resumo["receitas_realizadas"]
        total_despesas += resumo["despesas_realizadas"]

        for categoria, valor in resumo["por_categoria"].items():
            por_categoria[categoria] = por_categoria.get(categoria, ZERO) + valor

        linhas.append(
            {
                "ano": ano,
                "mes": mes,
                "receitas": resumo["receitas_realizadas"],
                "despesas": resumo["despesas_realizadas"],
                "saldo": resumo["saldo_realizado"],
                "taxa_poupanca": resumo["taxa_poupanca"],
            }
        )

    # Só meses com movimento entram na média e nos extremos: incluir o mês
    # vazio de quem começou a usar em junho puxaria a média para baixo e
    # apontaria "pior mês" para um mês que simplesmente não foi preenchido.
    com_movimento = [linha for linha in linhas if linha["receitas"] or linha["despesas"]]
    quantidade = len(com_movimento) or 1
    saldo = total_receitas - total_despesas

    return {
        "de": {"ano": competencias[0][0], "mes": competencias[0][1]},
        "ate": {"ano": ate_ano, "mes": ate_mes},
        "meses": linhas,
        "meses_com_movimento": len(com_movimento),
        "receitas": total_receitas,
        "despesas": total_despesas,
        "saldo": saldo,
        "media_receitas": (total_receitas / quantidade).quantize(Decimal("0.01")),
        "media_despesas": (total_despesas / quantidade).quantize(Decimal("0.01")),
        "media_saldo": (saldo / quantidade).quantize(Decimal("0.01")),
        "taxa_poupanca": (
            (saldo / total_receitas * 100).quantize(Decimal("0.01"))
            if total_receitas
            else ZERO
        ),
        "melhor_mes": max(com_movimento, key=lambda m: m["saldo"], default=None),
        "pior_mes": min(com_movimento, key=lambda m: m["saldo"], default=None),
        "por_categoria": por_categoria,
    }


def compromissos_assumidos(household, referencia: date | None = None) -> dict:
    """O que já está contratado daqui para a frente.

    Quem tem renda variável faz uma pergunta antes de qualquer decisão:
    "do que entra, quanto já está comprometido?". A resposta existia no
    cadastro das dívidas e em lugar nenhum na tela — e a parcela só aparecia
    no fluxo de caixa quando o mês dela chegava, um de cada vez.

    Considera apenas despesas fixas com fim previsto: é o compromisso que tem
    saldo a percorrer. Aluguel e escola são fixos, mas não são dívida com
    prazo — entram no fluxo do mês e não aqui.
    """
    hoje = referencia or date.today()
    atual = hoje.year * 12 + hoje.month

    itens = []
    total_mensal = ZERO
    total_restante = ZERO

    recorrentes = (
        RecurringExpense.objects.filter(household=household, ativa=True, divida__isnull=False)
        .select_related("divida")
        .order_by("vigencia_fim")
    )

    for recorrente in recorrentes:
        fim = recorrente.vigencia_fim
        inicio = recorrente.vigencia_inicio
        comeco = inicio.year * 12 + inicio.month

        if fim:
            termino = fim.year * 12 + fim.month
            if termino < atual:
                continue  # já terminou: não é mais compromisso
            faltam = termino - max(atual, comeco) + 1
        else:
            # Sem fim previsto (rotativo): não dá para somar o que falta, e
            # inventar um número seria pior que admitir que não se sabe.
            faltam = None

        mensal = recorrente.valor_previsto
        total_mensal += mensal
        if faltam is not None:
            total_restante += mensal * faltam

        itens.append(
            {
                "descricao": recorrente.descricao,
                "valor_mensal": mensal,
                "inicio": inicio,
                "fim": fim,
                "parcelas_restantes": faltam,
                "total_restante": (mensal * faltam) if faltam is not None else None,
                "ja_comecou": comeco <= atual,
            }
        )

    return {
        "itens": itens,
        "total_mensal": total_mensal,
        "total_restante": total_restante,
        # A data em que o orçamento alivia por completo, se todos tiverem fim.
        "livre_em": max((i["fim"] for i in itens if i["fim"]), default=None),
        "algum_sem_fim": any(i["parcelas_restantes"] is None for i in itens),
    }
