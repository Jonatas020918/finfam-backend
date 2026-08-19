"""Envia um e-mail de teste pela configuração atual.

Existe porque a falha de SMTP é silenciosa no lugar errado: a primeira vez que
o envio é exercitado de verdade costuma ser quando um cliente pede para
redefinir a senha — e aí ninguém fica sabendo que não chegou.

    python manage.py testar_email eu@meudominio.com.br
"""

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Envia um e-mail de teste para verificar a configuração de SMTP."

    def add_arguments(self, parser):
        parser.add_argument("destino", help="Endereço que vai receber o teste.")

    def handle(self, *args, **opcoes):
        destino = opcoes["destino"]
        console = "console" in settings.EMAIL_BACKEND

        self.stdout.write("Configuração em uso:")
        for rotulo, valor in [
            ("backend", settings.EMAIL_BACKEND.rsplit(".", 2)[-2]),
            ("host", settings.EMAIL_HOST or "(vazio)"),
            ("porta", settings.EMAIL_PORT),
            ("usuário", settings.EMAIL_HOST_USER or "(vazio)"),
            ("senha", "definida" if settings.EMAIL_HOST_PASSWORD else "(vazia)"),
            ("SSL", settings.EMAIL_USE_SSL),
            ("STARTTLS", settings.EMAIL_USE_TLS),
            ("remetente", settings.DEFAULT_FROM_EMAIL),
        ]:
            self.stdout.write(f"  {rotulo:.<14} {valor}")

        if console:
            self.stdout.write(
                self.style.WARNING(
                    "\nO backend é o console: o e-mail abaixo será impresso aqui e não "
                    "sairá da máquina. Defina EMAIL_HOST para testar o envio real."
                )
            )

        self.stdout.write(f"\nEnviando para {destino}...")
        try:
            enviados = send_mail(
                subject="Pulso — teste de configuração de e-mail",
                message=(
                    "Se você está lendo isto, o SMTP da plataforma está funcionando.\n\n"
                    "É o mesmo caminho que leva o link de redefinição de senha até o "
                    "cliente.\n\n— Pulso"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[destino],
                fail_silently=False,
            )
        except Exception as erro:  # noqa: BLE001 — a mensagem crua ajuda a diagnosticar
            raise CommandError(self._traduzir(erro)) from erro

        if not enviados:
            raise CommandError("O servidor aceitou a conexão mas não enviou nada.")

        if console:
            self.stdout.write(self.style.SUCCESS("\nImpresso acima (backend de console)."))
        else:
            self.stdout.write(
                self.style.SUCCESS(f"\nEnviado. Confira a caixa de {destino} — e o spam.")
            )
            self.stdout.write(
                "Se cair no spam, faltam os registros SPF, DKIM e DMARC no DNS do domínio."
            )

    @staticmethod
    def _traduzir(erro: Exception) -> str:
        """Erros de SMTP são crípticos; os três mais comuns ganham tradução."""
        texto = str(erro)
        dicas = {
            "authentication": (
                "Usuário ou senha recusados. EMAIL_HOST_USER precisa ser o endereço "
                "completo do mailbox, e a senha é a do mailbox — não a da conta do painel."
            ),
            "wrong version number": (
                "Porta e criptografia não combinam. A 465 usa EMAIL_USE_SSL; a 587 usa "
                "EMAIL_USE_TLS. Ligar o errado dá exatamente este erro."
            ),
            "timed out": (
                "Nada respondeu na porta. Confira o host e se a saída SMTP não está "
                "bloqueada pelo provedor do servidor."
            ),
        }
        for marca, dica in dicas.items():
            if marca in texto.lower():
                return f"{texto}\n\n→ {dica}"
        return texto
