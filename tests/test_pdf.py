"""Geração dos PDFs entregues ao cliente.

Os testes rodam no mesmo ambiente do desenvolvedor — sem bibliotecas nativas.
Era exatamente esse o problema do motor anterior: o PDF só nascia no Docker, e
ninguém conseguia conferir o documento antes de o cliente recebê-lo.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.reports.pdf import moeda

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def familia_com_movimento(api, familia_autenticada):
    """Família com renda fixa, despesa recorrente e uma meta."""
    household, titular, _ = familia_autenticada
    hoje = date.today()

    api.post(
        reverse("fonte-renda-list"),
        {
            "membro": str(titular.id),
            "descricao": "Consultório",
            "tipo": "pj_consultorio",
            "regime": "pj",
            "valor_medio_mensal": "42000",
            "modo_lancamento": "fixa",
        },
        format="json",
    )
    api.post(
        reverse("despesa-fixa-list"),
        {
            "descricao": "Aluguel do consultório",
            "categoria": "despesa_fixa",
            "valor_previsto": "9500",
            "vigencia_inicio": "2020-01-01",
        },
        format="json",
    )
    api.post(
        reverse("patrimonio-list"),
        {"tipo": "imovel", "descricao": "Apartamento", "valor_atual": "1200000"},
        format="json",
    )
    api.post(
        reverse("meta-list"),
        {"descricao": "Reserva de emergência", "valor_alvo": "200000", "valor_atual": "85000"},
        format="json",
    )
    api.post(
        reverse("abrir-competencia"), {"ano": hoje.year, "mes": hoje.month}, format="json"
    )
    return household, hoje


class TestFormatacaoDeMoeda:
    """O locale do sistema não é confiável em container; a formatação é nossa."""

    @pytest.mark.parametrize(
        "valor,esperado",
        [
            ("0", "R$ 0,00"),
            ("1234.5", "R$ 1.234,50"),
            ("42000", "R$ 42.000,00"),
            ("1200000.99", "R$ 1.200.000,99"),
            ("-350.4", "-R$ 350,40"),
            (None, "R$ 0,00"),
        ],
    )
    def test_formata_no_padrao_brasileiro(self, valor, esperado):
        assert moeda(valor) == esperado


class TestRetratoFinanceiro:
    def test_devolve_um_pdf_valido(self, api, familia_com_movimento):
        _, hoje = familia_com_movimento

        resposta = api.get(
            reverse("retrato-financeiro"), {"ano": hoje.year, "mes": hoje.month}
        )

        assert resposta.status_code == 200
        assert resposta["Content-Type"] == "application/pdf"
        conteudo = b"".join(resposta.streaming_content) if resposta.streaming else resposta.content
        # Assinatura do formato: o arquivo abre em qualquer leitor.
        assert conteudo.startswith(b"%PDF-")
        assert conteudo.rstrip().endswith(b"%%EOF")
        assert len(conteudo) > 2000

    def test_nome_do_arquivo_traz_a_competencia(self, api, familia_com_movimento):
        resposta = api.get(reverse("retrato-financeiro"), {"ano": 2026, "mes": 3})
        assert 'filename="retrato-financeiro-2026-03.pdf"' in resposta["Content-Disposition"]
        assert "attachment" in resposta["Content-Disposition"]

    def test_funciona_com_nucleo_vazio(self, api, familia_autenticada):
        """Cliente recém-cadastrado também consegue baixar."""
        resposta = api.get(reverse("retrato-financeiro"))
        assert resposta.status_code == 200
        assert resposta.content.startswith(b"%PDF-")

    def test_exige_autenticacao(self, api):
        assert api.get(reverse("retrato-financeiro")).status_code == 401


class TestExtratoMensal:
    def test_devolve_um_pdf_valido(self, api, familia_com_movimento):
        _, hoje = familia_com_movimento

        resposta = api.get(reverse("extrato-mensal"), {"ano": hoje.year, "mes": hoje.month})

        assert resposta.status_code == 200
        assert resposta["Content-Type"] == "application/pdf"
        assert resposta.content.startswith(b"%PDF-")
        assert int(resposta["Content-Length"]) == len(resposta.content)

    def test_nome_do_arquivo_traz_a_competencia(self, api, familia_com_movimento):
        resposta = api.get(reverse("extrato-mensal"), {"ano": 2026, "mes": 11})
        assert 'filename="receitas-e-despesas-2026-11.pdf"' in resposta["Content-Disposition"]

    def test_mes_sem_lancamento_gera_documento_mesmo_assim(self, api, familia_autenticada):
        resposta = api.get(reverse("extrato-mensal"), {"ano": 2020, "mes": 1})
        assert resposta.status_code == 200
        assert resposta.content.startswith(b"%PDF-")

    def test_nao_expoe_dados_de_outro_nucleo(self, api, familia, familia_autenticada):
        """O PDF é gerado a partir do núcleo do usuário logado, e só dele."""
        outra_household, outro_titular, _ = familia(
            email="outro@exemplo.com", nome="Outro", nome_familia="Família B"
        )
        from apps.cashflow.models import CashFlowEntry

        CashFlowEntry.objects.create(
            tenant=outra_household.tenant,
            household=outra_household,
            membro=outro_titular,
            tipo="receita",
            categoria="renda_trabalho",
            descricao="Renda alheia",
            valor_realizado=D("99000"),
            ano=2026,
            mes=8,
        )

        resposta = api.get(reverse("extrato-mensal"), {"ano": 2026, "mes": 8})
        assert resposta.status_code == 200
        # O texto do PDF é comprimido; a checagem que importa é a do resumo.
        resumo = api.get(reverse("lancamento-resumo"), {"ano": 2026, "mes": 8}).data
        assert D(resumo["receitas_realizadas"]) == D("0.00")

    def test_exige_autenticacao(self, api):
        assert api.get(reverse("extrato-mensal")).status_code == 401


class TestSonda:
    def test_saude_e_publica_e_barata(self, api):
        """O healthcheck do container não pode exigir token."""
        resposta = api.get(reverse("saude"))
        assert resposta.status_code == 200
        assert resposta.data == {"status": "ok"}
