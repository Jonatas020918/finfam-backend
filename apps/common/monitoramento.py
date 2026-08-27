"""Limpeza do evento de erro antes de ele sair da máquina.

Vive num módulo próprio, e não dentro do `settings`, para poder ser importado
pelo teste. Regra testada por cópia é regra não testada: a cópia continua
passando enquanto a original quebra — foi assim que um defeito de formato
chegou a produção nesta mesma base.
"""

#: Campos que nunca podem sair daqui. Isto é aplicação financeira: um
#: rastreamento com salário, patrimônio ou CPF dentro transforma a ferramenta
#: de monitoramento num vazamento de dado sensível — e sob a LGPD o titular
#: não consentiu com isso.
CAMPOS_SENSIVEIS = (
    "password",
    "senha",
    "token",
    "refresh",
    "access",
    "authorization",
    "credential",
    "cookie",
    "csrf",
    "documento",
    "cpf",
    "cnpj",
    "valor_realizado",
    "valor_bruto",
    "valor_orcado",
    "saldo_devedor",
    "valor_medio_mensal",
    "valor_parcela",
    "valor_previsto",
    "valor_atual",
    "cupom",
    "secret",
)


def limpar_evento(evento, _dica=None):
    """Substitui variável sensível capturada no rastreamento.

    `send_default_pii=False` já impede corpo de requisição e identidade do
    usuário, mas variável local capturada no stacktrace escapa disso — e é
    justamente onde o salário de alguém apareceria.
    """
    for excecao in (evento.get("exception") or {}).get("values") or []:
        for quadro in (excecao.get("stacktrace") or {}).get("frames") or []:
            variaveis = quadro.get("vars") or {}
            for nome in list(variaveis):
                if any(campo in nome.lower() for campo in CAMPOS_SENSIVEIS):
                    variaveis[nome] = "[removido]"
    return evento
