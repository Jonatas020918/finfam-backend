"""Fluxo de caixa, metas, dashboard, simulador via API e módulo educacional."""

from decimal import Decimal

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

D = Decimal


def _lancamento(api, **campos):
    payload = {"ano": 2026, "mes": 8, **campos}
    return api.post(reverse("lancamento-list"), payload, format="json")


class TestFluxoDeCaixa:
    def test_resumo_consolida_receitas_despesas_e_saldo(self, api, familia_autenticada):
        _, titular, _ = familia_autenticada
        _lancamento(api, membro=str(titular.id), tipo="receita",
                    categoria="renda_trabalho", descricao="Plantões",
                    valor_realizado="30000", valor_orcado="28000")
        _lancamento(api, tipo="despesa", categoria="despesa_fixa",
                    descricao="Aluguel", valor_realizado="8000", valor_orcado="8000")
        _lancamento(api, tipo="despesa", categoria="despesa_variavel",
                    descricao="Mercado", valor_realizado="4000", valor_orcado="3000")

        resumo = api.get(reverse("lancamento-resumo"), {"ano": 2026, "mes": 8}).data
        assert D(resumo["receitas_realizadas"]) == D("30000.00")
        assert D(resumo["despesas_realizadas"]) == D("12000.00")
        assert D(resumo["saldo_realizado"]) == D("18000.00")
        assert D(resumo["taxa_poupanca"]) == D("60.00")

    def test_resumo_separa_por_membro_e_compartilhado(self, api, familia_autenticada):
        _, titular, _ = familia_autenticada
        conjuge = api.post(
            reverse("membro-list"), {"tipo": "conjuge", "nome": "Bruno"}, format="json"
        ).data

        _lancamento(api, membro=str(titular.id), tipo="receita",
                    categoria="renda_trabalho", descricao="PJ", valor_realizado="40000")
        _lancamento(api, membro=conjuge["id"], tipo="receita",
                    categoria="renda_trabalho", descricao="CLT", valor_realizado="15000")
        _lancamento(api, tipo="despesa", categoria="despesa_fixa",
                    descricao="Escola", valor_realizado="5000")

        resumo = api.get(reverse("lancamento-resumo"), {"ano": 2026, "mes": 8}).data
        por_membro = {linha["membro_nome"]: linha for linha in resumo["por_membro"]}
        assert D(por_membro["Ana Souza"]["receitas"]) == D("40000.00")
        assert D(por_membro["Bruno"]["receitas"]) == D("15000.00")
        assert D(por_membro["Compartilhado (família)"]["despesas"]) == D("5000.00")

    def test_resumo_ignora_outros_meses(self, api, familia_autenticada):
        _lancamento(api, tipo="receita", categoria="renda_trabalho",
                    descricao="Julho", valor_realizado="1000", mes=7)
        resumo = api.get(reverse("lancamento-resumo"), {"ano": 2026, "mes": 8}).data
        assert D(resumo["receitas_realizadas"]) == D("0.00")

    def test_mes_invalido_e_rejeitado(self, api, familia_autenticada):
        resposta = _lancamento(api, tipo="receita", categoria="renda_trabalho",
                               descricao="X", valor_realizado="1", mes=13)
        assert resposta.status_code == 400


class TestMetas:
    def test_progresso_calculado_no_servidor(self, api, familia_autenticada):
        resposta = api.post(
            reverse("meta-list"),
            {"descricao": "Entrada do imóvel", "valor_alvo": "200000",
             "valor_atual": "50000"},
            format="json",
        )
        assert resposta.status_code == 201
        assert D(resposta.data["progresso_percentual"]) == D("25.00")
        assert resposta.data["compartilhada"] is True

    def test_progresso_limitado_a_100(self, api, familia_autenticada):
        resposta = api.post(
            reverse("meta-list"),
            {"descricao": "Reserva", "valor_alvo": "10000", "valor_atual": "15000"},
            format="json",
        )
        assert D(resposta.data["progresso_percentual"]) == D("100.00")

    def test_meta_individual_referencia_o_membro(self, api, familia_autenticada):
        _, titular, _ = familia_autenticada
        resposta = api.post(
            reverse("meta-list"),
            {"descricao": "Aposentadoria da Ana", "valor_alvo": "3000000",
             "membro": str(titular.id)},
            format="json",
        )
        assert resposta.data["compartilhada"] is False
        assert resposta.data["membro_nome"] == "Ana Souza"


class TestSimuladorViaAPI:
    def test_compara_os_tres_regimes(self, api, familia_autenticada):
        resposta = api.post(
            reverse("simulador-pj-clt"),
            {"receita_bruta_mensal": "45000", "dependentes": 2},
            format="json",
        )
        assert resposta.status_code == 200
        regimes = {r["regime"] for r in resposta.data["resultados"]}
        assert regimes == {"clt", "pj", "autonomo"}
        assert resposta.data["disclaimer"]

    def test_salvar_registra_no_historico_do_nucleo(self, api, familia_autenticada):
        household, titular, _ = familia_autenticada
        api.post(
            reverse("simulador-pj-clt"),
            {"receita_bruta_mensal": "45000", "salvar": True, "membro": str(titular.id)},
            format="json",
        )
        historico = api.get(reverse("simulacao-list")).data["results"]
        assert len(historico) == 1
        assert historico[0]["versao_regras"]

    def test_receita_zero_e_rejeitada(self, api, familia_autenticada):
        resposta = api.post(
            reverse("simulador-pj-clt"), {"receita_bruta_mensal": "0"}, format="json"
        )
        assert resposta.status_code == 400


class TestDashboard:
    def test_consolida_patrimonio_renda_fluxo_e_metas(self, api, familia_autenticada):
        _, titular, _ = familia_autenticada

        api.post(reverse("patrimonio-list"),
                 {"tipo": "imovel", "descricao": "Apto", "valor_atual": "1000000"},
                 format="json")
        api.post(reverse("divida-list"),
                 {"tipo": "financiamento_imovel", "descricao": "Financiamento",
                  "saldo_devedor": "400000"}, format="json")
        api.post(reverse("fonte-renda-list"),
                 {"membro": str(titular.id), "descricao": "Consultório",
                  "tipo": "pj_consultorio", "regime": "pj",
                  "valor_medio_mensal": "42000"}, format="json")
        api.post(reverse("meta-list"),
                 {"descricao": "Reserva", "valor_alvo": "100000", "valor_atual": "40000"},
                 format="json")
        _lancamento(api, tipo="receita", categoria="renda_trabalho",
                    descricao="Plantões", valor_realizado="42000")

        dados = api.get(reverse("dashboard"), {"ano": 2026, "mes": 8}).data
        assert D(dados["patrimonio"]["liquido"]) == D("600000.00")
        assert D(dados["renda"]["renda_combinada_mensal"]) == D("42000.00")
        assert D(dados["fluxo_caixa"]["receitas_realizadas"]) == D("42000.00")
        assert dados["metas"]["total_ativas"] == 1
        # Self-service: o bloco da consultoria aparece, mas como "em breve" —
        # a Fase 2 ainda não foi construída.
        assert dados["consultoria"] == {"convite_visivel": True, "disponivel": False}

    def test_flag_libera_a_oferta_de_consultoria(self, api, familia_autenticada, settings):
        """Quando a Fase 2 existir, virar a flag basta para o painel oferecê-la."""
        settings.CONSULTORIA_DISPONIVEL = True
        dados = api.get(reverse("dashboard")).data
        assert dados["consultoria"]["disponivel"] is True

    def test_dashboard_vazio_nao_quebra(self, api, familia_autenticada):
        dados = api.get(reverse("dashboard")).data
        assert D(dados["patrimonio"]["liquido"]) == D("0.00")
        assert dados["relatorio_educacional"] is None

    def test_retrato_financeiro_sai_em_pdf(self, api, familia_autenticada):
        """A pré-visualização em HTML existia porque o PDF só nascia no Docker.

        O gerador agora é Python puro e funciona em qualquer ambiente, então o
        endpoint entrega o próprio arquivo. Detalhes do documento ficam em
        tests/test_pdf.py.
        """
        resposta = api.get(reverse("retrato-financeiro"))
        assert resposta.status_code == 200
        assert resposta["Content-Type"] == "application/pdf"
        assert resposta.content.startswith(b"%PDF-")


class TestModuloEducacional:
    def test_lista_apenas_relatorios_publicados(self, api, familia_autenticada):
        from apps.education.models import EducationalReport, StatusRelatorio

        EducationalReport.objects.create(
            ano=2026, mes=7, titulo="Rascunho", status=StatusRelatorio.RASCUNHO
        )
        EducationalReport.objects.create(
            ano=2026, mes=6, titulo="Publicado", status=StatusRelatorio.PUBLICADO,
            secoes=[{"titulo": "Panorama", "corpo": "Texto educacional."}],
        )
        titulos = [
            r["titulo"] for r in api.get(reverse("relatorio-educacional-list")).data["results"]
        ]
        assert titulos == ["Publicado"]

    def test_relatorio_sempre_carrega_disclaimer(self, api, familia_autenticada):
        from apps.education.models import DISCLAIMER_PADRAO, EducationalReport, StatusRelatorio

        EducationalReport.objects.create(
            ano=2026, mes=6, titulo="Publicado", status=StatusRelatorio.PUBLICADO,
            secoes=[{"titulo": "Panorama", "corpo": "Texto."}],
        )
        atual = api.get(reverse("relatorio-educacional-atual")).data
        assert atual["disclaimer"] == DISCLAIMER_PADRAO

    def test_aceite_do_disclaimer_fica_registrado(self, api, familia_autenticada):
        resposta = api.post(reverse("aceitar-disclaimer"))
        assert resposta.status_code == 200
        assert resposta.data["aceite_disclaimer_educacional_em"]
