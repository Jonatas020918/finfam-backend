"""O monitoramento não pode virar um vazamento.

Rastreamento de erro captura variáveis locais — e numa aplicação financeira é
exatamente ali que salário, patrimônio e CPF aparecem. Enviar isso para um
serviço externo seria tratar dado que o titular não consentiu em compartilhar,
com o agravante de que ninguém veria acontecer.

Os testes chamam a função que roda de verdade, importada do módulo. Testar uma
cópia da regra é o mesmo que não testar: a cópia continua passando enquanto a
original quebra.
"""

from apps.common.monitoramento import limpar_evento


def _evento(variaveis: dict) -> dict:
    """Um evento no formato que o SDK monta ao capturar exceção."""
    return {"exception": {"values": [{"stacktrace": {"frames": [{"vars": variaveis}]}}]}}


def _vars(evento: dict) -> dict:
    return evento["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]


class TestLimpezaDeDadoSensivel:
    def test_remove_senha_e_token(self):
        limpo = limpar_evento(_evento({"senha": "muito-secreta", "token": "eyJhbGc", "mes": 8}))

        assert _vars(limpo)["senha"] == "[removido]"
        assert _vars(limpo)["token"] == "[removido]"
        # O que não é sensível fica: sem contexto nenhum o erro não se depura.
        assert _vars(limpo)["mes"] == 8

    def test_remove_valores_financeiros(self):
        """Salário e patrimônio são o dado mais sensível que a plataforma guarda."""
        limpo = limpar_evento(
            _evento(
                {
                    "valor_realizado": "24000.00",
                    "saldo_devedor": "50000.00",
                    "documento": "12345678909",
                }
            )
        )

        assert all(valor == "[removido]" for valor in _vars(limpo).values())

    def test_pega_o_campo_dentro_de_nome_composto(self):
        """`dados_senha` e `novo_cpf` também precisam sair."""
        limpo = limpar_evento(_evento({"dados_senha": "x", "novo_cpf": "y"}))

        assert _vars(limpo)["dados_senha"] == "[removido]"
        assert _vars(limpo)["novo_cpf"] == "[removido]"

    def test_evento_sem_rastreamento_nao_quebra(self):
        """Nem todo evento tem exceção — mensagem solta também passa por aqui."""
        assert limpar_evento({"message": "algo aconteceu"}) == {"message": "algo aconteceu"}

    def test_quadro_sem_variaveis_nao_quebra(self):
        evento = {"exception": {"values": [{"stacktrace": {"frames": [{}]}}]}}
        assert limpar_evento(evento) == evento


class TestDesligadoPorPadrao:
    def test_sem_dsn_nada_e_enviado(self, settings):
        """Desenvolvimento e teste não podem mandar nada para lugar nenhum."""
        assert settings.SENTRY_DSN == ""
