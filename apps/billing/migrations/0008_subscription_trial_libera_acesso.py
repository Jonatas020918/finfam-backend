"""Cartão passa a ser pedido no cadastro — sem tirar ninguém de dentro.

A regra nova é: conta nova escolhe plano e testa pelo Stripe, com cartão. Mas
quem já estava usando entrou sob a regra antiga, em que o teste local abria a
plataforma sem cartão nenhum. Aplicar a regra nova a essas contas as poria
para fora da porta de um dia para o outro, por uma decisão que elas não
tomaram.

Por isso o campo nasce `False` (a regra nova) e esta migração marca `True` em
tudo que já existe. É uma marcação de uma vez só: nada depois disso volta a
escrever `True`, então a exceção não se espalha.
"""

from django.db import migrations, models


def preservar_acesso_das_contas_atuais(apps, schema_editor):
    Subscription = apps.get_model("billing", "Subscription")
    Subscription.objects.update(trial_libera_acesso=True)


def reverter(apps, schema_editor):
    """Volta todo mundo para a regra nova.

    Só existe para o `migrate` reverso não travar. Se for preciso desfazer de
    verdade, o acesso das contas antigas some junto — por isso a reversão é
    explícita, e não silenciosa.
    """
    Subscription = apps.get_model("billing", "Subscription")
    Subscription.objects.update(trial_libera_acesso=False)


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0007_reajusta_planos_e_oculta_intermediario'),
    ]

    operations = [
        migrations.AddField(
            model_name='subscription',
            name='trial_libera_acesso',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(preservar_acesso_das_contas_atuais, reverter),
    ]
