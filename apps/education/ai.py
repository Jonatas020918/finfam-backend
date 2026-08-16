"""Geração do texto do relatório educacional via Claude (seção 3.6).

Limites que o prompt precisa impor — são requisito de compliance, não estilo:
  - conteúdo educacional, nunca recomendação personalizada;
  - nenhum produto específico é citado, apenas categorias;
  - nenhum número macroeconômico é inventado: só os que passamos aqui.

A saída entra no banco como RASCUNHO. A revisão humana antes de publicar é
obrigatória (seção 3.6).
"""

import json

from django.conf import settings

from .bcb import IndicadoresMes
from .models import DISCLAIMER_PADRAO

MESES = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]

SYSTEM_PROMPT = f"""Você redige o relatório mensal educacional de uma plataforma
de organização financeira para médicos e profissionais de saúde no Brasil.

REGRAS INEGOCIÁVEIS:
1. O conteúdo é exclusivamente EDUCACIONAL e INFORMATIVO. Nunca recomende
   investimentos, nunca sugira alocação, nunca use verbos como "invista",
   "prefira", "aproveite para aplicar".
2. Nunca cite produtos específicos (nomes de fundos, bancos, títulos de emissor
   específico). Fale apenas de CATEGORIAS (renda fixa pós-fixada, prefixada,
   indexada à inflação, renda variável, previdência).
3. Use SOMENTE os indicadores fornecidos no input. Não estime, não projete e não
   cite nenhum outro número macroeconômico.
4. Linguagem simples, para quem não é do mercado financeiro. Frases curtas.
5. Explique o que cada conceito significa na prática para um profissional
   autônomo ou PJ que não tem INSS robusto — sempre como fato educacional.

Disclaimer que acompanha o relatório (não repita no corpo): "{DISCLAIMER_PADRAO}"

Responda SOMENTE com JSON válido no formato:
{{"titulo": str,
  "secoes": [{{"titulo": str, "corpo": str}}],
  "glossario": [{{"termo": str, "definicao": str}}]}}

Seções esperadas, nesta ordem: "Panorama macroeconômico",
"O que isso significa na prática", "Panorama por categoria de investimento",
"Contexto para quem é autônomo ou PJ".
"""


def montar_prompt(ind: IndicadoresMes) -> str:
    mes_nome = MESES[ind.mes - 1]
    dados = {
        "mes_referencia": f"{mes_nome} de {ind.ano}",
        "selic_meta_ao_ano_percentual": str(ind.selic_meta),
        "variacao_selic_no_mes_pontos_percentuais": str(ind.selic_variacao_mes),
        "ipca_do_mes_percentual": str(ind.ipca_mes),
        "ipca_acumulado_12_meses_percentual": str(ind.ipca_12m),
        "fonte": "Banco Central do Brasil — Sistema Gerenciador de Séries Temporais",
    }
    return (
        "Redija o relatório educacional do mês com base exclusivamente nestes "
        "dados oficiais:\n\n" + json.dumps(dados, ensure_ascii=False, indent=2)
    )


def gerar_conteudo(ind: IndicadoresMes) -> dict:
    """Chama a API da Anthropic e devolve o conteúdo estruturado.

    Levanta RuntimeError se a chave não estiver configurada — preferimos falhar
    a task a publicar um relatório vazio.
    """
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY não configurada.")

    from anthropic import Anthropic

    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    resposta = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": montar_prompt(ind)}],
    )
    texto = "".join(bloco.text for bloco in resposta.content if bloco.type == "text")
    return json.loads(texto)
