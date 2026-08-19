"""Geração dos PDFs entregues ao cliente (seção 3.9).

Construídos com ReportLab, em Python puro. A escolha é deliberada: o WeasyPrint
gera páginas mais bonitas a partir de HTML, mas depende de Pango, Cairo e
GDK-Pixbuf — bibliotecas nativas que existem na imagem Docker e não no Windows.
Na prática isso significava um botão que funcionava em produção e quebrava na
máquina de quem desenvolve. Um relatório que só nasce em um ambiente é um
relatório que ninguém revisa antes de o cliente receber.

São dois documentos:

  retrato financeiro — a fotografia completa (patrimônio, renda, metas, dívidas)
  extrato mensal     — o que entrou e saiu em uma competência, item a item
"""

from datetime import date
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Paleta da marca, espelhando o produto: quem recebe o PDF precisa reconhecer
# de onde ele veio.
NOITE = colors.HexColor("#0b1e2d")
AZUL = colors.HexColor("#1b52c0")
PULSO = colors.HexColor("#ff6b4a")
TINTA = colors.HexColor("#17212f")
TINTA_2 = colors.HexColor("#4a5f75")
LINHA = colors.HexColor("#dde5ef")
FUNDO_SUAVE = colors.HexColor("#f2f6fb")
VERDE = colors.HexColor("#0f6f50")
VERMELHO = colors.HexColor("#b3261e")

MESES = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]

DISCLAIMER = (
    "Este documento tem caráter exclusivamente educacional e informativo. Não constitui "
    "recomendação de investimento, oferta ou análise personalizada. Decisões de investimento "
    "devem ser tomadas com apoio de profissional certificado pela CVM, considerando o perfil "
    "individual do investidor. As simulações tributárias são simplificações para fins de "
    "planejamento e não substituem orientação contábil formal."
)


# --- Formatação ------------------------------------------------------------

def moeda(valor) -> str:
    """R$ 1.234,56 — separadores brasileiros, sem depender de locale do sistema."""
    numero = Decimal(str(valor or 0)).quantize(Decimal("0.01"))
    inteiro, _, centavos = f"{abs(numero):.2f}".partition(".")
    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    sinal = "-" if numero < 0 else ""
    return f"{sinal}R$ {'.'.join(grupos)},{centavos}"


def _percentual(valor) -> str:
    return f"{Decimal(str(valor or 0)).quantize(Decimal('0.01'))}%"


def _competencia(ano: int, mes: int) -> str:
    return f"{MESES[mes - 1]} de {ano}"


# --- Estilos ---------------------------------------------------------------

def _estilos() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle(
        "base", fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=TINTA
    )
    return {
        "titulo": ParagraphStyle(
            "titulo", parent=base, fontName="Helvetica-Bold", fontSize=20, leading=24,
            textColor=NOITE, spaceAfter=2,
        ),
        "subtitulo": ParagraphStyle(
            "subtitulo", parent=base, fontSize=10, textColor=TINTA_2, spaceAfter=14,
        ),
        "secao": ParagraphStyle(
            "secao", parent=base, fontName="Helvetica-Bold", fontSize=12, leading=16,
            textColor=NOITE, spaceBefore=16, spaceAfter=6,
        ),
        "corpo": base,
        "apoio": ParagraphStyle("apoio", parent=base, fontSize=8.5, textColor=TINTA_2),
        "celula": ParagraphStyle("celula", parent=base, fontSize=9),
        "celula_dir": ParagraphStyle("celula_dir", parent=base, fontSize=9, alignment=TA_RIGHT),
        "disclaimer": ParagraphStyle(
            "disclaimer", parent=base, fontSize=7.5, leading=10.5, textColor=TINTA_2,
        ),
    }


def _decoracao(nome_documento: str):
    """Cabeçalho da marca e rodapé com paginação, repetidos em toda página."""

    def desenhar(canvas, doc):
        canvas.saveState()
        largura, altura = A4

        # Faixa da marca
        canvas.setFillColor(NOITE)
        canvas.rect(0, altura - 18 * mm, largura, 18 * mm, stroke=0, fill=1)

        # Traço do eletrocardiograma, o mesmo sinal da interface
        canvas.setStrokeColor(PULSO)
        canvas.setLineWidth(1.6)
        base_y = altura - 9 * mm
        caminho = canvas.beginPath()
        caminho.moveTo(16 * mm, base_y)
        for dx, dy in [(4, 0), (5.5, 3.2), (7, -4.6), (8.5, 0), (13, 0)]:
            caminho.lineTo((16 + dx) * mm, base_y + dy * mm)
        canvas.drawPath(caminho)

        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(32 * mm, base_y - 1.5 * mm, "Pulso")

        canvas.setFont("Helvetica", 8.5)
        canvas.setFillColor(colors.HexColor("#a9bed3"))
        canvas.drawRightString(largura - 16 * mm, base_y - 1.5 * mm, nome_documento)

        # Rodapé
        canvas.setFillColor(TINTA_2)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(
            16 * mm, 12 * mm, f"Gerado em {date.today().strftime('%d/%m/%Y')}"
        )
        canvas.drawRightString(largura - 16 * mm, 12 * mm, f"Página {doc.page}")
        canvas.setStrokeColor(LINHA)
        canvas.setLineWidth(0.5)
        canvas.line(16 * mm, 16 * mm, largura - 16 * mm, 16 * mm)

        canvas.restoreState()

    return desenhar


def _documento(buffer: BytesIO, titulo: str) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=26 * mm,
        bottomMargin=22 * mm,
        title=titulo,
        author="Pulso",
    )


def _tabela(dados, larguras, estilo_extra=None) -> Table:
    tabela = Table(dados, colWidths=larguras, repeatRows=1, hAlign="LEFT")
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), FUNDO_SUAVE),
        ("TEXTCOLOR", (0, 0), (-1, 0), TINTA_2),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINHA),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    tabela.setStyle(TableStyle(estilo + (estilo_extra or [])))
    return tabela


def _cartoes_kpi(itens: list[tuple[str, str]], largura_total: float) -> Table:
    """Faixa de números-destaque no topo do documento."""
    linhas = [
        [Paragraph(f"<font size=7.5 color='#4a5f75'>{rotulo.upper()}</font>", _estilos()["apoio"])
         for rotulo, _ in itens],
        [Paragraph(f"<font size=14 color='#0b1e2d'><b>{valor}</b></font>", _estilos()["corpo"])
         for _, valor in itens],
    ]
    largura = largura_total / len(itens)
    tabela = Table(linhas, colWidths=[largura] * len(itens), hAlign="LEFT")
    tabela.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), FUNDO_SUAVE),
                ("BOX", (0, 0), (-1, -1), 0.5, LINHA),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 9),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    return tabela


# --- Retrato financeiro ----------------------------------------------------

def gerar_retrato_financeiro(dashboard: dict, anotacoes: str | None = None) -> bytes:
    """Fotografia completa da situação da família."""
    estilos = _estilos()
    buffer = BytesIO()
    doc = _documento(buffer, "Retrato financeiro")
    largura = doc.width

    ano = dashboard["referencia"]["ano"]
    mes = dashboard["referencia"]["mes"]
    patrimonio = dashboard["patrimonio"]
    fluxo = dashboard["fluxo_caixa"]
    renda = dashboard["renda"]

    elementos = [
        Paragraph("Retrato financeiro", estilos["titulo"]),
        Paragraph(
            f"{dashboard['household']['nome']} — posição de {_competencia(ano, mes)}",
            estilos["subtitulo"],
        ),
        _cartoes_kpi(
            [
                ("Patrimônio líquido", moeda(patrimonio["liquido"])),
                ("Renda da família", moeda(renda["renda_combinada_mensal"])),
                ("Saldo do mês", moeda(fluxo["saldo_realizado"])),
            ],
            largura,
        ),
        Spacer(1, 4 * mm),
    ]

    # --- Patrimônio
    elementos.append(Paragraph("Patrimônio", estilos["secao"]))
    linhas = [["Composição", "Valor"]]
    linhas.append(["Bens e aplicações", moeda(patrimonio["ativos"])])
    linhas.append(["Dívidas", f"({moeda(patrimonio['dividas'])})"])
    linhas.append(["Patrimônio líquido", moeda(patrimonio["liquido"])])
    elementos.append(
        _tabela(
            linhas,
            [largura * 0.6, largura * 0.4],
            [
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 0.8, TINTA_2),
                ("TEXTCOLOR", (1, 2), (1, 2), VERMELHO),
            ],
        )
    )

    if patrimonio.get("por_categoria"):
        rotulos = {
            "imovel": "Imóveis", "veiculo": "Veículos", "aplicacao": "Aplicações financeiras",
            "participacao": "Participações societárias", "previdencia": "Previdência",
            "outro": "Outros",
        }
        linhas = [["Onde está o patrimônio", "Valor"]]
        for tipo, valor in sorted(
            patrimonio["por_categoria"].items(), key=lambda item: -float(item[1])
        ):
            linhas.append([rotulos.get(tipo, tipo), moeda(valor)])
        elementos += [
            Spacer(1, 3 * mm),
            _tabela(linhas, [largura * 0.6, largura * 0.4], [("ALIGN", (1, 0), (1, -1), "RIGHT")]),
        ]

    # --- Renda
    elementos.append(Paragraph("Renda por membro", estilos["secao"]))
    if renda["por_membro"]:
        linhas = [["Membro", "Renda mensal", "Participação"]]
        for membro in renda["por_membro"]:
            linhas.append(
                [
                    membro["membro_nome"],
                    moeda(membro["renda_media_mensal"]),
                    _percentual(membro["participacao_percentual"]),
                ]
            )
        elementos.append(
            _tabela(
                linhas,
                [largura * 0.5, largura * 0.28, largura * 0.22],
                [("ALIGN", (1, 0), (-1, -1), "RIGHT")],
            )
        )
    else:
        elementos.append(Paragraph("Nenhuma fonte de renda cadastrada.", estilos["apoio"]))

    # --- Fluxo do mês
    elementos.append(Paragraph(f"Fluxo de caixa de {_competencia(ano, mes)}", estilos["secao"]))
    linhas = [["", "Realizado", "Orçado"]]
    linhas.append(["Receitas", moeda(fluxo["receitas_realizadas"]), moeda(fluxo["receitas_orcadas"])])
    linhas.append(["Despesas", moeda(fluxo["despesas_realizadas"]), moeda(fluxo["despesas_orcadas"])])
    linhas.append(["Saldo", moeda(fluxo["saldo_realizado"]), moeda(fluxo["saldo_orcado"])])
    elementos.append(
        _tabela(
            linhas,
            [largura * 0.4, largura * 0.3, largura * 0.3],
            [
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 0.8, TINTA_2),
            ],
        )
    )
    elementos.append(
        Paragraph(
            f"Taxa de poupança do mês: {_percentual(fluxo['taxa_poupanca'])} do que entrou.",
            estilos["apoio"],
        )
    )

    # --- Metas
    metas = dashboard["metas"]["metas"]
    elementos.append(Paragraph("Metas", estilos["secao"]))
    if metas:
        linhas = [["Meta", "Acumulado", "Objetivo", "Progresso"]]
        for meta in metas:
            linhas.append(
                [
                    Paragraph(str(meta["descricao"]), estilos["celula"]),
                    moeda(meta["valor_atual"]),
                    moeda(meta["valor_alvo"]),
                    _percentual(meta["progresso_percentual"]),
                ]
            )
        elementos.append(
            _tabela(
                linhas,
                [largura * 0.4, largura * 0.2, largura * 0.2, largura * 0.2],
                [("ALIGN", (1, 0), (-1, -1), "RIGHT")],
            )
        )
    else:
        elementos.append(Paragraph("Nenhuma meta ativa.", estilos["apoio"]))

    # --- Financiamentos
    dividas = dashboard.get("dividas", {}).get("itens", [])
    if dividas:
        elementos.append(Paragraph("Financiamentos", estilos["secao"]))
        linhas = [["Contrato", "Saldo devedor", "Parcela", "Pagas", "Faltam"]]
        for divida in dividas:
            linhas.append(
                [
                    Paragraph(str(divida["descricao"]), estilos["celula"]),
                    moeda(divida["saldo_devedor"]),
                    moeda(divida["valor_parcela"]),
                    str(divida["parcelas_pagas"] or "—"),
                    str(divida["parcelas_a_pagar"] or "—"),
                ]
            )
        elementos.append(
            _tabela(
                linhas,
                [largura * 0.34, largura * 0.22, largura * 0.18, largura * 0.13, largura * 0.13],
                [("ALIGN", (1, 0), (-1, -1), "RIGHT")],
            )
        )

    if anotacoes:
        elementos.append(Paragraph("Anotações do consultor", estilos["secao"]))
        elementos.append(Paragraph(anotacoes.replace("\n", "<br/>"), estilos["corpo"]))

    elementos += [Spacer(1, 8 * mm), Paragraph(DISCLAIMER, estilos["disclaimer"])]

    doc.build(elementos, onFirstPage=_decoracao("Retrato financeiro"),
              onLaterPages=_decoracao("Retrato financeiro"))
    return buffer.getvalue()


# --- Extrato mensal --------------------------------------------------------

ROTULOS_CATEGORIA = {
    "renda_trabalho": "Renda do trabalho",
    "renda_investimento": "Renda de investimentos",
    "outra_receita": "Outra receita",
    "despesa_fixa": "Despesa fixa",
    "despesa_variavel": "Despesa variável",
    "investimento": "Investimento",
    "divida": "Pagamento de dívida",
    "imposto": "Impostos",
}


def gerar_extrato_mensal(household_nome: str, ano: int, mes: int, resumo: dict, lancamentos) -> bytes:
    """Receitas e despesas de uma competência, item a item.

    O documento que o cliente leva ao contador: cada lançamento, de onde veio
    (fixo ou variável) e a que vínculo tributário pertence.
    """
    estilos = _estilos()
    buffer = BytesIO()
    doc = _documento(buffer, f"Receitas e despesas {mes:02d}/{ano}")
    largura = doc.width

    receitas = [item for item in lancamentos if item.tipo == "receita"]
    despesas = [item for item in lancamentos if item.tipo == "despesa"]

    elementos = [
        Paragraph("Receitas e despesas", estilos["titulo"]),
        Paragraph(f"{household_nome} — {_competencia(ano, mes)}", estilos["subtitulo"]),
        _cartoes_kpi(
            [
                ("Receitas", moeda(resumo["receitas_realizadas"])),
                ("Despesas", moeda(resumo["despesas_realizadas"])),
                ("Saldo", moeda(resumo["saldo_realizado"])),
            ],
            largura,
        ),
        Spacer(1, 4 * mm),
    ]

    def bloco(titulo: str, itens, mostrar_vinculo: bool):
        partes = [Paragraph(titulo, estilos["secao"])]
        if not itens:
            partes.append(Paragraph("Nenhum lançamento nesta competência.", estilos["apoio"]))
            return partes

        cabecalho = ["Descrição", "Categoria", "De quem", "Origem"]
        larguras = [largura * 0.30, largura * 0.20, largura * 0.18, largura * 0.14]
        if mostrar_vinculo:
            cabecalho[3] = "Vínculo"
        cabecalho.append("Valor")
        larguras.append(largura * 0.18)

        linhas = [cabecalho]
        total = Decimal("0")
        for item in itens:
            total += Decimal(str(item.valor_realizado))
            origem = item.get_regime_display() if (mostrar_vinculo and item.regime) else (
                "Fixo" if item.recorrente else "Variável"
            )
            linhas.append(
                [
                    Paragraph(item.descricao, estilos["celula"]),
                    Paragraph(ROTULOS_CATEGORIA.get(item.categoria, item.categoria), estilos["celula"]),
                    Paragraph(item.membro.nome if item.membro_id else "Família", estilos["celula"]),
                    Paragraph(origem, estilos["celula"]),
                    moeda(item.valor_realizado),
                ]
            )
        linhas.append(["Total", "", "", "", moeda(total)])

        partes.append(
            _tabela(
                linhas,
                larguras,
                [
                    ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                    ("LINEABOVE", (0, -1), (-1, -1), 0.8, TINTA_2),
                ],
            )
        )
        return partes

    elementos += bloco("Receitas", receitas, mostrar_vinculo=True)
    elementos += bloco("Despesas", despesas, mostrar_vinculo=False)

    # --- Orçado x realizado: o comparativo que a tela mostra no topo
    elementos.append(Paragraph("Orçado x realizado", estilos["secao"]))
    linhas = [
        ["", "Orçado", "Realizado", "Diferença"],
        [
            "Receitas",
            moeda(resumo["receitas_orcadas"]),
            moeda(resumo["receitas_realizadas"]),
            moeda(
                Decimal(str(resumo["receitas_realizadas"]))
                - Decimal(str(resumo["receitas_orcadas"]))
            ),
        ],
        [
            "Despesas",
            moeda(resumo["despesas_orcadas"]),
            moeda(resumo["despesas_realizadas"]),
            moeda(
                Decimal(str(resumo["despesas_realizadas"]))
                - Decimal(str(resumo["despesas_orcadas"]))
            ),
        ],
        [
            "Saldo",
            moeda(resumo["saldo_orcado"]),
            moeda(resumo["saldo_realizado"]),
            moeda(
                Decimal(str(resumo["saldo_realizado"])) - Decimal(str(resumo["saldo_orcado"]))
            ),
        ],
    ]
    elementos.append(
        _tabela(
            linhas,
            [largura * 0.28, largura * 0.24, largura * 0.24, largura * 0.24],
            [
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 0.8, TINTA_2),
            ],
        )
    )
    elementos.append(
        Paragraph(
            f"Taxa de poupança do mês: {_percentual(resumo['taxa_poupanca'])} do que entrou.",
            estilos["apoio"],
        )
    )

    # --- Para onde foi o dinheiro
    categorias_despesa = {
        categoria: valor
        for categoria, valor in (resumo.get("por_categoria") or {}).items()
        if categoria in {"despesa_fixa", "despesa_variavel", "investimento", "divida", "imposto"}
    }
    if categorias_despesa:
        elementos.append(Paragraph("Para onde foi o dinheiro", estilos["secao"]))
        total_despesas = sum(Decimal(str(v)) for v in categorias_despesa.values())
        linhas = [["Categoria", "Valor", "Participação"]]
        for categoria, valor in sorted(categorias_despesa.items(), key=lambda i: -float(i[1])):
            fatia = (Decimal(str(valor)) / total_despesas * 100) if total_despesas else Decimal("0")
            linhas.append(
                [
                    ROTULOS_CATEGORIA.get(categoria, categoria),
                    moeda(valor),
                    _percentual(fatia.quantize(Decimal("0.01"))),
                ]
            )
        elementos.append(
            _tabela(
                linhas,
                [largura * 0.5, largura * 0.28, largura * 0.22],
                [("ALIGN", (1, 0), (-1, -1), "RIGHT")],
            )
        )

    # --- Quebra por membro
    if resumo.get("por_membro"):
        elementos.append(Paragraph("Por membro da família", estilos["secao"]))
        linhas = [["Membro", "Receitas", "Despesas", "Saldo"]]
        for linha in resumo["por_membro"]:
            linhas.append(
                [
                    linha["membro_nome"],
                    moeda(linha["receitas"]),
                    moeda(linha["despesas"]),
                    moeda(linha["saldo"]),
                ]
            )
        elementos.append(
            _tabela(
                linhas,
                [largura * 0.4, largura * 0.2, largura * 0.2, largura * 0.2],
                [("ALIGN", (1, 0), (-1, -1), "RIGHT")],
            )
        )

    # --- Renda por vínculo: é o que alimenta o simulador
    if resumo.get("por_regime"):
        elementos.append(Paragraph("Renda por vínculo tributário", estilos["secao"]))
        linhas = [["Vínculo", "Receitas", "Participação"]]
        for linha in resumo["por_regime"]:
            linhas.append(
                [
                    linha["rotulo"],
                    moeda(linha["receitas"]),
                    _percentual(linha["participacao_percentual"]),
                ]
            )
        if Decimal(str(resumo.get("receitas_nao_classificadas", 0))) > 0:
            linhas.append(
                ["Sem classificação", moeda(resumo["receitas_nao_classificadas"]), "—"]
            )
        elementos.append(
            _tabela(
                linhas,
                [largura * 0.5, largura * 0.28, largura * 0.22],
                [("ALIGN", (1, 0), (-1, -1), "RIGHT")],
            )
        )

    elementos += [Spacer(1, 8 * mm), Paragraph(DISCLAIMER, estilos["disclaimer"])]

    nome = f"Receitas e despesas {mes:02d}/{ano}"
    doc.build(elementos, onFirstPage=_decoracao(nome), onLaterPages=_decoracao(nome))
    return buffer.getvalue()


__all__ = ["gerar_retrato_financeiro", "gerar_extrato_mensal", "moeda", "PageBreak", "KeepTogether"]
