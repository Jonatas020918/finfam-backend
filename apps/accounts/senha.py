"""Redefinição de senha por e-mail.

Usa o `PasswordResetTokenGenerator` do Django: o token é derivado do hash da
senha atual, do último login e de um timestamp, então **expira sozinho** quando
a senha muda ou quando o prazo passa — não precisa de tabela nem de limpeza.

Duas decisões de segurança que valem explicitar:

*Não revelamos se o e-mail existe.* A resposta é idêntica para conta existente
e inexistente. Um formulário que responde "e-mail não cadastrado" é uma API de
descoberta de clientes — e a base aqui é de médicos, cuja lista tem valor
comercial para terceiros.

*O link leva ao frontend, não à API.* Quem clica precisa cair numa tela, não num
JSON; o backend só valida o par (uid, token) quando o formulário volta.
"""

from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from .models import User

gerador_de_token = PasswordResetTokenGenerator()

ASSUNTO = "Redefinição de senha — Batimento"

CORPO = """Olá, {nome}.

Recebemos um pedido para redefinir a senha da sua conta no Batimento.

Abra o link abaixo para escolher uma nova senha:

{link}

O link vale por {horas} horas e deixa de funcionar assim que você o utilizar.

Se não foi você que pediu, ignore esta mensagem — sua senha atual continua
valendo e ninguém teve acesso à sua conta.

Batimento — organização financeira para quem tem renda variável
"""


def montar_link(user: User) -> str:
    """URL da tela de nova senha, no frontend."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = gerador_de_token.make_token(user)
    base = settings.FRONTEND_URL.rstrip("/")
    return f"{base}/nova-senha?uid={uid}&token={token}"


def enviar_email_de_redefinicao(user: User) -> None:
    horas = settings.PASSWORD_RESET_TIMEOUT // 3600
    send_mail(
        subject=ASSUNTO,
        message=CORPO.format(
            nome=user.nome_completo.split()[0], link=montar_link(user), horas=horas
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )


def solicitar_redefinicao(email: str) -> bool:
    """Dispara o e-mail quando a conta existe. Devolve se algo foi enviado.

    O chamador **não** deve expor esse retorno na resposta HTTP: ele existe para
    log e para teste, não para o cliente saber se o e-mail está cadastrado.
    """
    user = User.objects.filter(email__iexact=email.strip(), is_active=True).first()
    if user is None:
        return False
    enviar_email_de_redefinicao(user)
    return True


def usuario_do_token(uid: str, token: str) -> User | None:
    """Valida o par (uid, token) e devolve o usuário, ou None."""
    try:
        pk = force_str(urlsafe_base64_decode(uid))
        user = User.objects.get(pk=pk, is_active=True)
    # O pk é UUID: um uid corrompido levanta ValidationError na consulta, e não
    # apenas ValueError. Capturamos junto para o endpoint responder 400, não 500.
    except (TypeError, ValueError, OverflowError, ValidationError, User.DoesNotExist):
        return None

    if not gerador_de_token.check_token(user, token):
        return None
    return user
