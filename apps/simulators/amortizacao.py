"""Simulação de quitação e amortização de financiamentos.

Cobre os dois sistemas usados no Brasil:

  Price — parcela fixa; no começo quase tudo é juro e pouco abate o saldo.
          Padrão em financiamento de veículo e crédito pessoal.
  SAC   — amortização constante e parcela decrescente; é o mais comum em
          financiamento imobiliário pela Caixa.

Motor puro: nenhuma dependência de banco ou request, para ser testável isolado e
reutilizável no relatório em PDF.

O ponto de partida é sempre o **saldo devedor atual** e as **parcelas que faltam**,
não o contrato original — é o que o cliente consegue informar com precisão
olhando o extrato, e é o que importa para decidir sobre amortizar.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

D = Decimal
ZERO = D("0.00")
CENTAVO = D("0.01")


def _brl(valor: Decimal) -> Decimal:
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


class EstrategiaAporte:
    """O que fazer com o dinheiro que sobra ao amortizar."""

    REDUZIR_PRAZO = "reduzir_prazo"
    REDUZIR_PARCELA = "reduzir_parcela"


@dataclass
class Parcela:
    numero: int
    juros: Decimal
    amortizacao: Decimal
    valor: Decimal
    saldo_final: Decimal
    amortizacao_extra: Decimal = ZERO


@dataclass
class Cenario:
    """Resultado de um caminho de pagamento até a quitação."""

    parcelas_restantes: int
    total_pago: Decimal
    total_juros: Decimal
    primeira_parcela: Decimal
    ultima_parcela: Decimal
    cronograma: list[Parcela] = field(default_factory=list)

    def resumo_serializavel(self, limite_cronograma: int = 360) -> dict:
        return {
            "parcelas_restantes": self.parcelas_restantes,
            "total_pago": _brl(self.total_pago),
            "total_juros": _brl(self.total_juros),
            "primeira_parcela": _brl(self.primeira_parcela),
            "ultima_parcela": _brl(self.ultima_parcela),
            "cronograma": [
                {
                    "numero": p.numero,
                    "juros": _brl(p.juros),
                    "amortizacao": _brl(p.amortizacao),
                    "amortizacao_extra": _brl(p.amortizacao_extra),
                    "valor": _brl(p.valor),
                    "saldo_final": _brl(p.saldo_final),
                }
                for p in self.cronograma[:limite_cronograma]
            ],
        }


def parcela_price(saldo: Decimal, taxa_mensal: Decimal, parcelas: int) -> Decimal:
    """Parcela fixa do sistema Price: PMT = SD × i ÷ (1 − (1+i)^−n)."""
    if parcelas <= 0:
        return ZERO
    if taxa_mensal <= 0:
        return _brl(saldo / parcelas)
    fator = (1 + taxa_mensal) ** parcelas
    return _brl(saldo * taxa_mensal * fator / (fator - 1))


def gerar_cronograma(
    saldo_devedor: Decimal,
    taxa_mensal: Decimal,
    parcelas: int,
    sistema: str = "price",
    aporte_extra_mensal: Decimal = ZERO,
    aporte_unico: Decimal = ZERO,
    estrategia: str = EstrategiaAporte.REDUZIR_PRAZO,
    limite_iteracoes: int = 1200,
) -> Cenario:
    """Simula mês a mês até o saldo zerar.

    `aporte_unico` entra antes da primeira parcela; `aporte_extra_mensal` se
    soma a cada pagamento. Amortização extra sempre abate saldo (nunca juros
    futuros), que é como funciona na prática.

    Com REDUZIR_PRAZO a parcela continua igual e o contrato termina antes; com
    REDUZIR_PARCELA o prazo é mantido e a parcela é recalculada — a primeira
    opção economiza mais juros, a segunda alivia o mês.
    """
    saldo = Decimal(saldo_devedor)
    taxa = Decimal(taxa_mensal)
    extra_mensal = Decimal(aporte_extra_mensal)

    if saldo <= 0 or parcelas <= 0:
        return Cenario(0, ZERO, ZERO, ZERO, ZERO, [])

    # A parcela contratual nasce do saldo ANTES de qualquer aporte: amortizar
    # não faz o banco recalcular a prestação sozinho. Ou o prazo encurta
    # (parcela intacta), ou a parcela cai — e isso é escolha do cliente.
    amortizacao_sac = saldo / parcelas if sistema == "sac" else None
    pmt = parcela_price(saldo, taxa, parcelas) if sistema != "sac" else None

    saldo = max(saldo - Decimal(aporte_unico), ZERO)
    if saldo <= 0:
        # O aporte único quitou o financiamento.
        return Cenario(0, _brl(aporte_unico), ZERO, ZERO, ZERO, [])

    tem_aporte = extra_mensal > 0 or Decimal(aporte_unico) > 0
    cronograma: list[Parcela] = []
    total_pago = Decimal(aporte_unico)
    total_juros = ZERO
    numero = 0
    restantes_contratuais = parcelas

    while saldo > CENTAVO and numero < limite_iteracoes:
        numero += 1
        juros = _brl(saldo * taxa)

        recalcular = estrategia == EstrategiaAporte.REDUZIR_PARCELA and tem_aporte

        if sistema == "sac":
            if recalcular:
                # Prazo mantido: a amortização se redistribui no que resta.
                amortizacao_sac = saldo / restantes_contratuais
            amortizacao = min(amortizacao_sac, saldo)
            valor = _brl(amortizacao + juros)
        else:
            if recalcular:
                # Prazo mantido: a parcela é recalculada sobre o saldo atual.
                pmt = parcela_price(saldo, taxa, restantes_contratuais)
            valor = min(pmt, _brl(saldo + juros))
            amortizacao = valor - juros

        extra = ZERO
        if extra_mensal > 0:
            extra = min(extra_mensal, max(saldo - amortizacao, ZERO))

        saldo = _brl(saldo - amortizacao - extra)
        if saldo < CENTAVO:
            saldo = ZERO

        total_pago += valor + extra
        total_juros += juros
        restantes_contratuais = max(restantes_contratuais - 1, 1)

        cronograma.append(
            Parcela(
                numero=numero,
                juros=juros,
                amortizacao=_brl(amortizacao),
                valor=_brl(valor + extra),
                saldo_final=saldo,
                amortizacao_extra=_brl(extra),
            )
        )

    return Cenario(
        parcelas_restantes=len(cronograma),
        total_pago=total_pago,
        total_juros=total_juros,
        primeira_parcela=cronograma[0].valor if cronograma else ZERO,
        ultima_parcela=cronograma[-1].valor if cronograma else ZERO,
        cronograma=cronograma,
    )


def _somar_meses(inicio: date, meses: int) -> date:
    from calendar import monthrange

    ano = inicio.year + (inicio.month - 1 + meses) // 12
    mes = (inicio.month - 1 + meses) % 12 + 1
    dia = min(inicio.day, monthrange(ano, mes)[1])
    return date(ano, mes, dia)


def simular_amortizacao(
    saldo_devedor: Decimal,
    taxa_mensal_percentual: Decimal,
    parcelas_restantes: int,
    sistema: str = "price",
    aporte_extra_mensal: Decimal = ZERO,
    aporte_unico: Decimal = ZERO,
    estrategia: str = EstrategiaAporte.REDUZIR_PRAZO,
    parcelas_pagas: int = 0,
    parcelas_totais: int = 0,
    referencia: date | None = None,
) -> dict:
    """Compara seguir no ritmo atual x antecipar pagamento.

    Devolve os dois cenários, o quanto se economiza em juros e em tempo, e a
    posição atual do contrato (quantas parcelas já foram e quantas faltam) —
    que é a pergunta que a pessoa realmente faz ao olhar o financiamento.
    """
    taxa = Decimal(taxa_mensal_percentual) / 100
    referencia = referencia or date.today()
    parcelas_totais = parcelas_totais or (parcelas_pagas + parcelas_restantes)

    atual = gerar_cronograma(saldo_devedor, taxa, parcelas_restantes, sistema)

    tem_aporte = Decimal(aporte_extra_mensal) > 0 or Decimal(aporte_unico) > 0
    acelerado = (
        gerar_cronograma(
            saldo_devedor,
            taxa,
            parcelas_restantes,
            sistema,
            aporte_extra_mensal=aporte_extra_mensal,
            aporte_unico=aporte_unico,
            estrategia=estrategia,
        )
        if tem_aporte
        else None
    )

    meses_economizados = (
        atual.parcelas_restantes - acelerado.parcelas_restantes if acelerado else 0
    )
    juros_economizados = (
        _brl(atual.total_juros - acelerado.total_juros) if acelerado else ZERO
    )

    progresso = (
        (Decimal(parcelas_pagas) / Decimal(parcelas_totais) * 100).quantize(CENTAVO)
        if parcelas_totais
        else ZERO
    )

    resultado = {
        "posicao": {
            "parcelas_pagas": parcelas_pagas,
            "parcelas_restantes": atual.parcelas_restantes,
            "parcelas_totais": parcelas_totais,
            "progresso_percentual": progresso,
            "saldo_devedor": _brl(Decimal(saldo_devedor)),
            "quitacao_prevista": _somar_meses(referencia, atual.parcelas_restantes),
        },
        "sistema": sistema,
        "cenario_atual": atual.resumo_serializavel(),
        "cenario_com_aporte": acelerado.resumo_serializavel() if acelerado else None,
        "economia": {
            "meses": meses_economizados,
            "juros": juros_economizados,
            "anos_texto": _texto_meses(meses_economizados),
            "nova_quitacao": (
                _somar_meses(referencia, acelerado.parcelas_restantes) if acelerado else None
            ),
        }
        if acelerado
        else None,
        "estrategia": estrategia if acelerado else None,
        "disclaimer": (
            "Simulação baseada nos dados informados por você e em juros constantes. "
            "Contratos reais podem ter seguro, taxa de administração e correção "
            "(TR ou IPCA) que alteram o resultado — confirme os números no extrato "
            "do seu contrato antes de decidir."
        ),
    }
    return resultado


def _texto_meses(meses: int) -> str:
    if meses <= 0:
        return "nenhum mês"
    anos, resto = divmod(meses, 12)
    partes = []
    if anos:
        partes.append(f"{anos} ano{'s' if anos > 1 else ''}")
    if resto:
        partes.append(f"{resto} {'meses' if resto > 1 else 'mês'}")
    return " e ".join(partes)
