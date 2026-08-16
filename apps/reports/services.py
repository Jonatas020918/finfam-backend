"""Consolidação do dashboard e snapshot do relatório em PDF (seções 3.7 e 3.9)."""

from datetime import date
from decimal import Decimal

from django.db.models import Sum

from apps.cashflow.services import resumo_mensal
from apps.education.models import EducationalReport, StatusRelatorio
from apps.goals.models import Goal
from apps.households.models import Asset, Debt, IncomeSource

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
        "convite_consultoria": household.modo == "self_service",
    }
