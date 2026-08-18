"""Sincronização e exposição dos indicadores oficiais do Banco Central.

A rede é sempre simulada: o teste não pode depender do BCB estar no ar, e
precisa cobrir justamente o caso em que ele não está.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.education.bcb import IndicadoresMes
from apps.education.models import IndicadorMensal
from apps.education.services import _competencias_recentes, sincronizar_indicadores

pytestmark = pytest.mark.django_db

D = Decimal


def _dados(ano, mes, selic="14.25", ipca="0.35", ipca12="4.40", variacao="0.00"):
    return IndicadoresMes(
        ano=ano,
        mes=mes,
        selic_meta=D(selic) if selic else None,
        selic_variacao_mes=D(variacao) if variacao else None,
        ipca_mes=D(ipca) if ipca else None,
        ipca_12m=D(ipca12) if ipca12 else None,
    )


class TestJanelaDeCompetencias:
    def test_ordena_da_mais_antiga_para_a_mais_recente(self):
        assert _competencias_recentes(date(2026, 8, 17), 3) == [
            (2026, 6),
            (2026, 7),
            (2026, 8),
        ]

    def test_atravessa_a_virada_de_ano(self):
        assert _competencias_recentes(date(2026, 2, 5), 4) == [
            (2025, 11),
            (2025, 12),
            (2026, 1),
            (2026, 2),
        ]


class TestSincronizacao:
    @patch("apps.education.services.coletar_indicadores")
    def test_grava_uma_competencia_por_mes(self, mock_coletar):
        mock_coletar.side_effect = lambda ano, mes: _dados(ano, mes)

        atualizados = sincronizar_indicadores(meses=3, referencia=date(2026, 8, 17))

        assert len(atualizados) == 3
        assert IndicadorMensal.objects.count() == 3
        assert set(IndicadorMensal.objects.values_list("mes", flat=True)) == {6, 7, 8}

    @patch("apps.education.services.coletar_indicadores")
    def test_rodar_de_novo_atualiza_em_vez_de_duplicar(self, mock_coletar):
        """O IPCA do mês só sai lá pelo dia 10 — a competência é revisitada."""
        mock_coletar.side_effect = lambda ano, mes: _dados(ano, mes, ipca=None, ipca12=None)
        sincronizar_indicadores(meses=1, referencia=date(2026, 8, 5))

        indicador = IndicadorMensal.objects.get(ano=2026, mes=8)
        assert indicador.ipca_mes_percentual is None
        assert indicador.completo is False

        mock_coletar.side_effect = lambda ano, mes: _dados(ano, mes, ipca="0.28")
        sincronizar_indicadores(meses=1, referencia=date(2026, 8, 12))

        assert IndicadorMensal.objects.count() == 1
        indicador.refresh_from_db()
        assert indicador.ipca_mes_percentual == D("0.28")
        assert indicador.completo is True

    @patch("apps.education.services.coletar_indicadores")
    def test_falha_em_um_mes_nao_derruba_os_outros(self, mock_coletar):
        def coletar(ano, mes):
            if mes == 7:
                raise ConnectionError("BCB fora do ar")
            return _dados(ano, mes)

        mock_coletar.side_effect = coletar
        atualizados = sincronizar_indicadores(meses=3, referencia=date(2026, 8, 17))

        assert len(atualizados) == 2
        assert not IndicadorMensal.objects.filter(mes=7).exists()

    @patch("apps.education.services.coletar_indicadores")
    def test_serie_indisponivel_nao_apaga_valor_ja_salvo(self, mock_coletar):
        """O IPCA já publicado não pode sumir porque a consulta de hoje falhou."""
        mock_coletar.side_effect = lambda ano, mes: _dados(ano, mes, ipca="0.31")
        sincronizar_indicadores(meses=1, referencia=date(2026, 8, 17))

        mock_coletar.side_effect = lambda ano, mes: _dados(
            ano, mes, selic="13.75", ipca=None, ipca12=None
        )
        sincronizar_indicadores(meses=1, referencia=date(2026, 8, 17))

        indicador = IndicadorMensal.objects.get(ano=2026, mes=8)
        assert indicador.selic_meta_percentual == D("13.75")  # atualizou
        assert indicador.ipca_mes_percentual == D("0.31")  # preservou

    @patch("apps.education.services.coletar_indicadores")
    def test_bcb_totalmente_indisponivel_nao_grava_nada(self, mock_coletar):
        mock_coletar.side_effect = ConnectionError("sem rede")
        assert sincronizar_indicadores(meses=3) == []
        assert IndicadorMensal.objects.count() == 0


class TestMaisRecentes:
    def test_cada_indicador_traz_a_propria_referencia(self):
        """Selic do mês corrente convive com IPCA do mês anterior."""
        IndicadorMensal.objects.create(
            ano=2026, mes=7, selic_meta_percentual=D("14.25"),
            ipca_mes_percentual=D("0.26"), ipca_12m_percentual=D("4.40"),
        )
        IndicadorMensal.objects.create(
            ano=2026, mes=8, selic_meta_percentual=D("13.75"),
            ipca_mes_percentual=None, ipca_12m_percentual=None,
        )

        atuais = IndicadorMensal.mais_recentes()
        assert atuais["selic_meta"]["valor"] == "13.75"
        assert atuais["selic_meta"]["referencia"] == "08/2026"
        # O IPCA de agosto ainda não saiu; vale o de julho, identificado como tal.
        assert atuais["ipca_mes"]["valor"] == "0.26"
        assert atuais["ipca_mes"]["referencia"] == "07/2026"

    def test_sem_dado_devolve_nulo_em_vez_de_quebrar(self):
        atuais = IndicadorMensal.mais_recentes()
        assert atuais["selic_meta"] is None
        assert atuais["ipca_mes"] is None


class TestEndpoint:
    def test_expoe_atuais_e_historico_em_ordem_cronologica(self, api, familia_autenticada):
        for mes in (6, 7, 8):
            IndicadorMensal.objects.create(
                ano=2026, mes=mes,
                selic_meta_percentual=D("14.25"),
                ipca_mes_percentual=D("0.30"),
                ipca_12m_percentual=D("4.40"),
            )

        dados = api.get(reverse("indicadores")).data

        assert dados["atuais"]["selic_meta"]["referencia"] == "08/2026"
        assert [i["mes"] for i in dados["historico"]] == [6, 7, 8]
        assert dados["series_utilizadas"]["ipca_mensal"] == 433
        assert "Banco Central" in dados["fonte"]

    def test_independe_de_relatorio_publicado(self, api, familia_autenticada):
        """O ponto da separação: número oficial não espera revisão editorial."""
        IndicadorMensal.objects.create(
            ano=2026, mes=8, selic_meta_percentual=D("13.75"),
            ipca_mes_percentual=D("0.19"), ipca_12m_percentual=D("4.10"),
        )
        from apps.education.models import EducationalReport

        assert not EducationalReport.objects.filter(status="publicado").exists()

        dados = api.get(reverse("indicadores")).data
        assert dados["atuais"]["selic_meta"]["valor"] == "13.75"

    def test_limita_o_tamanho_do_historico(self, api, familia_autenticada):
        for mes in range(1, 13):
            IndicadorMensal.objects.create(
                ano=2026, mes=mes, selic_meta_percentual=D("14.25")
            )
        dados = api.get(reverse("indicadores"), {"meses": 4}).data
        assert len(dados["historico"]) == 4

    def test_exige_autenticacao(self, api):
        assert api.get(reverse("indicadores")).status_code == 401


class TestTaskAgendada:
    @patch("apps.education.tasks.sincronizar_indicadores")
    def test_task_delega_para_o_servico(self, mock_sincronizar):
        from apps.education.tasks import atualizar_indicadores

        mock_sincronizar.return_value = [
            IndicadorMensal(ano=2026, mes=8, selic_meta_percentual=D("14.25"))
        ]
        resultado = atualizar_indicadores.apply(kwargs={"meses": 2}).get()

        mock_sincronizar.assert_called_once_with(meses=2)
        assert resultado == ["08/2026"]
