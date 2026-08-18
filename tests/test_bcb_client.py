"""Cliente do SGS do Banco Central.

Não toca a rede: o comportamento que interessa aqui é como reagimos às
respostas do BCB, e isso precisa ser verificável sem depender de o serviço
estar no ar.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

import httpx
import pytest

from apps.education.bcb import SERIE_IPCA_MENSAL, coletar_indicadores

D = Decimal


def _resposta(status: int, corpo=None):
    resposta = Mock(spec=httpx.Response)
    resposta.status_code = status
    resposta.json.return_value = corpo or []
    if status >= 400 and status != 404:
        resposta.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"erro {status}", request=Mock(), response=resposta
        )
    else:
        resposta.raise_for_status.return_value = None
    return resposta


class TestColetaDeIndicadores:
    @patch("apps.education.bcb.httpx.get")
    def test_le_selic_e_ipca_do_periodo(self, mock_get):
        mock_get.return_value = _resposta(
            200, [{"data": "01/07/2026", "valor": "14.25"}, {"data": "31/07/2026", "valor": "14.25"}]
        )

        indicadores = coletar_indicadores(2026, 7)

        assert indicadores.selic_meta == D("14.25")
        assert indicadores.selic_variacao_mes == D("0.00")
        assert indicadores.completo is True

    @patch("apps.education.bcb.httpx.get")
    def test_variacao_da_selic_no_mes(self, mock_get):
        """Copom cortou no meio do mês: a variação precisa aparecer."""
        mock_get.return_value = _resposta(
            200, [{"data": "01/03/2026", "valor": "15.00"}, {"data": "31/03/2026", "valor": "14.75"}]
        )

        indicadores = coletar_indicadores(2026, 3)
        assert indicadores.selic_variacao_mes == D("-0.25")

    @patch("apps.education.bcb.httpx.get")
    def test_ipca_do_mes_corrente_ainda_nao_publicado(self, mock_get):
        """O caso real: 404 no IPCA não pode derrubar a coleta da Selic.

        O BCB responde 404 quando a série não tem dado no intervalo, e o IPCA de
        um mês só sai por volta do dia 10 do mês seguinte.
        """

        def responder(url, **kwargs):
            if str(SERIE_IPCA_MENSAL) in url:
                return _resposta(404)
            return _resposta(200, [{"data": "01/08/2026", "valor": "14.25"}])

        mock_get.side_effect = responder

        indicadores = coletar_indicadores(2026, 8)

        assert indicadores.selic_meta == D("14.25")
        assert indicadores.ipca_mes is None
        assert indicadores.completo is False

    @patch("apps.education.bcb.httpx.get")
    def test_erro_de_servidor_continua_propagando(self, mock_get):
        """502 é indisponibilidade, não ausência de dado — o job deve tentar de novo."""
        mock_get.return_value = _resposta(502)

        with pytest.raises(httpx.HTTPStatusError):
            coletar_indicadores(2026, 7)

    @patch("apps.education.bcb.httpx.get")
    def test_intervalo_cobre_o_mes_pedido(self, mock_get):
        mock_get.return_value = _resposta(200, [{"data": "01/12/2026", "valor": "10.00"}])

        coletar_indicadores(2026, 12)

        params = mock_get.call_args.kwargs["params"]
        assert params["dataInicial"] == "01/12/2026"
        # Dezembro precisa virar o ano na data final.
        assert params["dataFinal"] == "01/01/2027"

    @patch("apps.education.bcb.httpx.get")
    def test_serie_vazia_devolve_nulo_sem_quebrar(self, mock_get):
        mock_get.return_value = _resposta(200, [])

        indicadores = coletar_indicadores(2026, 7)

        assert indicadores.selic_meta is None
        assert indicadores.ipca_mes is None
        assert indicadores.completo is False


def test_usa_o_mes_e_ano_informados():
    """Guarda contra troca acidental de ano/mês na assinatura."""
    with patch("apps.education.bcb.httpx.get") as mock_get:
        mock_get.return_value = _resposta(200, [{"data": "01/05/2025", "valor": "1"}])
        indicadores = coletar_indicadores(2025, 5)

    assert (indicadores.ano, indicadores.mes) == (2025, 5)
    assert date(2025, 5, 1)  # sanidade do fixture de data
