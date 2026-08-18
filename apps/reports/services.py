"""Consolidação do dashboard e snapshot do relatório em PDF (seções 3.7 e 3.9)."""

from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db.models import Q, Sum

from apps.cashflow.models import CashFlowEntry
from apps.cashflow.services import resumo_mensal
from apps.education.models import EducationalReport, StatusRelatorio
from apps.goals.models import Goal
from apps.households.models import Asset, Debt, IncomeSource  # noqa: F401

ZERO = Decimal("0.00")


def _total(qs, campo) -> Decimal:
    return qs.aggregate(t=Sum(campo))["t"] or ZERO


def patrimonio_liquido(household) -> dict:
    """Ativos − dívidas, com quebra por membro/titularidade."""
    ativos = Asset.objects.filter(household=household)
    dividas = Debt.objects.filter(household=household)
    total_ativos = _total(ativos, "valor_atual")
    total_dividas = _total(dividas, "saldo_devedor")

    por_membro = []
    for membro in household.membros.all():
        a = _total(ativos.filter(membro=membro), "valor_atual")
        d = _total(dividas.filter(membro=membro), "saldo_devedor")
        if a or d:
            por_membro.append(
                {
                    "membro_id": str(membro.id),
                    "membro_nome": membro.nome,
                    "ativos": a,
                    "dividas": d,
                    "liquido": a - d,
                }
            )

    return {
        "ativos": total_ativos,
        "dividas": total_dividas,
        "liquido": total_ativos - total_dividas,
        "por_membro": por_membro,
        "por_categoria": {
            linha["tipo"]: linha["total"]
            for linha in ativos.values("tipo").annotate(total=Sum("valor_atual"))
        },
    }


def renda_da_familia(household) -> dict:
    """Renda combinada declarada no onboarding e a contribuição de cada membro."""
    fontes = IncomeSource.objects.filter(household=household, ativa=True)
    total = _total(fontes, "valor_medio_mensal")
    por_membro = []
    for membro in household.membros.all():
        valor = _total(fontes.filter(membro=membro), "valor_medio_mensal")
        if valor:
            participacao = (valor / total * 100) if total else ZERO
            por_membro.append(
                {
                    "membro_id": str(membro.id),
                    "membro_nome": membro.nome,
                    "renda_media_mensal": valor,
                    "participacao_percentual": participacao.quantize(Decimal("0.01")),
                }
            )
    return {"renda_combinada_mensal": total, "por_membro": por_membro}


def resumo_dividas(household) -> dict:
    """Financiamentos com posição de pagamento — insumo do painel e do PDF."""
    itens = []
    for divida in Debt.objects.filter(household=household).order_by("-saldo_devedor"):
        itens.append(
            {
                "id": str(divida.id),
                "descricao": divida.descricao,
                "tipo": divida.get_tipo_display(),
                "saldo_devedor": divida.saldo_devedor,
                "valor_parcela": divida.valor_parcela,
                "parcelas_pagas": divida.parcelas_pagas,
                "parcelas_a_pagar": divida.parcelas_a_pagar,
                "parcelas_totais": divida.parcelas_totais,
                "progresso_percentual": divida.progresso_percentual,
                "data_quitacao_prevista": divida.data_quitacao_prevista,
            }
        )
    return {
        "total_saldo": _total(Debt.objects.filter(household=household), "saldo_devedor"),
        "total_parcela_mensal": _total(
            Debt.objects.filter(household=household), "valor_parcela"
        ),
        "itens": itens,
    }


def resumo_metas(household) -> dict:
    metas = Goal.objects.filter(household=household, concluida=False)
    itens = [
        {
            "id": str(m.id),
            "descricao": m.descricao,
            "valor_alvo": m.valor_alvo,
            "valor_atual": m.valor_atual,
            "progresso_percentual": m.progresso_percentual,
            "compartilhada": m.compartilhada,
            "membro_nome": m.membro.nome if m.membro_id else None,
            "data_alvo": m.data_alvo,
        }
        for m in metas.select_related("membro")
    ]
    return {"total_ativas": len(itens), "metas": itens}


MESES_ABREV = [
    "jan", "fev", "mar", "abr", "mai", "jun",
    "jul", "ago", "set", "out", "nov", "dez",
]


def historico_mensal(household, ano: int, mes: int, meses: int = 12) -> list[dict]:
    """Série temporal de receitas, despesas e saldo até o mês de referência.

    Uma única consulta agregada, e não um resumo por mês: com 12 pontos, o
    caminho ingênuo faria dezenas de queries só para desenhar um gráfico.
    """
    inicio_ano, inicio_mes = ano, mes - meses + 1
    while inicio_mes <= 0:
        inicio_mes += 12
        inicio_ano -= 1

    lancamentos = CashFlowEntry.objects.filter(household=household).filter(
        Q(ano__gt=inicio_ano) | Q(ano=inicio_ano, mes__gte=inicio_mes),
        Q(ano__lt=ano) | Q(ano=ano, mes__lte=mes),
    )
    agregado = lancamentos.values("ano", "mes", "tipo").annotate(total=Sum("valor_realizado"))

    por_competencia: dict[tuple[int, int], dict[str, Decimal]] = {}
    for linha in agregado:
        chave = (linha["ano"], linha["mes"])
        por_competencia.setdefault(chave, {"receita": ZERO, "despesa": ZERO})
        por_competencia[chave][linha["tipo"]] = linha["total"] or ZERO

    serie = []
    cursor_ano, cursor_mes = inicio_ano, inicio_mes
    for _ in range(meses):
        valores = por_competencia.get((cursor_ano, cursor_mes), {})
        receitas = valores.get("receita", ZERO)
        despesas = valores.get("despesa", ZERO)
        serie.append(
            {
                "ano": cursor_ano,
                "mes": cursor_mes,
                "rotulo": f"{MESES_ABREV[cursor_mes - 1]}/{str(cursor_ano)[2:]}",
                "receitas": receitas,
                "despesas": despesas,
                "saldo": receitas - despesas,
            }
        )
        cursor_mes += 1
        if cursor_mes > 12:
            cursor_mes = 1
            cursor_ano += 1
    return serie


def medias_do_periodo(household, ano: int, mes: int, meses: int) -> dict:
    """Médias mensais de receita e despesa na janela escolhida.

    Meses sem lançamento entram na conta como zero de propósito: um mês em que
    nada foi registrado é um mês sem sobra, e ignorá-lo inflaria a média.
    """
    serie = historico_mensal(household, ano, mes, meses)
    receitas = sum((linha["receitas"] for linha in serie), ZERO)
    despesas = sum((linha["despesas"] for linha in serie), ZERO)
    divisor = Decimal(len(serie) or 1)
    return {
        "receitas_medias": (receitas / divisor).quantize(Decimal("0.01")),
        "despesas_medias": (despesas / divisor).quantize(Decimal("0.01")),
        "serie": serie,
    }


def montar_dashboard(household, ano: int | None = None, mes: int | None = None) -> dict:
    """Payload único do dashboard do cliente (seção 3.7)."""
    hoje = date.today()
    ano = ano or hoje.year
    mes = mes or hoje.month

    relatorio = (
        EducationalReport.objects.filter(status=StatusRelatorio.PUBLICADO)
        .order_by("-ano", "-mes")
        .first()
    )

    return {
        "household": {
            "id": str(household.id),
            "nome": household.nome,
            "modo": household.modo,
            "onboarding_concluido": household.onboarding_concluido,
        },
        "referencia": {"ano": ano, "mes": mes},
        "patrimonio": patrimonio_liquido(household),
        "fluxo_caixa": resumo_mensal(household, ano, mes),
        "historico": historico_mensal(household, ano, mes),
        "dividas": resumo_dividas(household),
        "renda": renda_da_familia(household),
        "metas": resumo_metas(household),
        "relatorio_educacional": (
            {
                "id": str(relatorio.id),
                "titulo": relatorio.titulo,
                "ano": relatorio.ano,
                "mes": relatorio.mes,
                "resumo": (relatorio.secoes[0]["corpo"][:400] if relatorio.secoes else ""),
                "disclaimer": relatorio.disclaimer,
            }
            if relatorio
            else None
        ),
        # Fase 2 preenche a próxima revisão; no self-service é o convite de upsell.
        "proxima_revisao": None,
        "consultoria": {
            # Mostra o bloco só para quem ainda não tem consultor.
            "convite_visivel": household.modo == "self_service",
            # Enquanto for falso, o bloco anuncia "em breve" em vez de oferecer
            # contratação — a Fase 2 ainda não existe (seção 7.2).
            "disponivel": settings.CONSULTORIA_DISPONIVEL,
        },
    }
