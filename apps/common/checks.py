"""Verificações que impedem subir em produção com uma configuração calada.

O padrão desta base é conveniente em desenvolvimento — e-mail vai para o
console, qualquer Host é aceito — e essa mesma conveniência, esquecida no
deploy, não dá erro nenhum: o servidor sobe, a API responde 200, e só o cliente
descobre que o e-mail de redefinição nunca chegou.

Cada verificação aqui transforma um desses silêncios em falha na hora do
`manage.py check --deploy`, antes de qualquer usuário encostar no sistema.
"""

from django.conf import settings
from django.core.checks import Error, Warning, register

CONSOLE = "django.core.mail.backends.console.EmailBackend"


@register(deploy=True)
def email_precisa_sair_da_maquina(app_configs, **kwargs):
    """Sem SMTP, a redefinição de senha falha sem avisar ninguém."""
    if settings.DEBUG or settings.EMAIL_BACKEND != CONSOLE:
        return []
    return [
        Error(
            "E-mail configurado para o console em produção.",
            hint=(
                "Defina EMAIL_HOST (e usuário/senha) no .env. Do jeito que está, "
                "o link de redefinição de senha é impresso no log do container e "
                "o cliente nunca o recebe — sem nenhum erro visível."
            ),
            id="finfam.E001",
        )
    ]


@register(deploy=True)
def hosts_precisam_ser_explicitos(app_configs, **kwargs):
    """`*` aceita qualquer Host, o que abre espaço para envenenar links."""
    if settings.DEBUG or "*" not in settings.ALLOWED_HOSTS:
        return []
    return [
        Error(
            "ALLOWED_HOSTS aceita qualquer domínio.",
            hint=(
                "Liste os domínios reais em ALLOWED_HOSTS. Com '*', um Host "
                "forjado entra no link de redefinição de senha que enviamos."
            ),
            id="finfam.E002",
        )
    ]


@register(deploy=True)
def cobranca_precisa_de_gateway_real(app_configs, **kwargs):
    """O mock libera acesso sem cobrar — em produção, isso é receita perdida."""
    if settings.DEBUG or "Mock" not in settings.ASSINATURA_GATEWAY:
        return []
    return [
        Warning(
            "Gateway de pagamento em modo simulado.",
            hint=(
                "ASSINATURA_GATEWAY aponta para o mock: nenhuma cobrança é feita "
                "de verdade. Troque para GatewayStripe e preencha STRIPE_SECRET_KEY "
                "e STRIPE_WEBHOOK_SECRET quando for começar a vender."
            ),
            id="finfam.W001",
        )
    ]
