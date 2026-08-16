"""Geração do PDF do retrato financeiro (seção 3.9).

WeasyPrint converte um template HTML/CSS renderizado pelo Django. A importação
é adiada porque a biblioteca exige libs de sistema (presentes na imagem Docker,
nem sempre no ambiente local de teste).
"""

from django.template.loader import render_to_string


def renderizar_html(contexto: dict) -> str:
    return render_to_string("reports/retrato_financeiro.html", contexto)


def gerar_pdf(contexto: dict, base_url: str | None = None) -> bytes:
    from weasyprint import HTML  # import adiado: depende de libs nativas

    html = renderizar_html(contexto)
    return HTML(string=html, base_url=base_url).write_pdf()
