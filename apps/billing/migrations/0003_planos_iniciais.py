"""Cria o plano self-service e dá teste às contas que já existem.

O preço entra como zero de propósito: é uma decisão comercial, não técnica, e
um número inventado aqui apareceria na interface como se fosse oficial. Ajuste
pelo admin antes de abrir vendas.
"""

from datetime import date, timedelta

from django.db import migrations

TRIAL_DIAS = 14


def criar_plano_e_assinaturas(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    Subscription = apps.get_model("billing", "Subscription")
    Household = apps.get_model("households", "Household")

    plano, _ = Plan.objects.get_or_create(
        codigo="self_service",
        defaults={
            "nome": "Pulso Self-service",
            "preco_mensal": 0,
            "descricao": (
                "Organização financeira familiar, simuladores, projeção e módulo "
                "educacional. Defina o preço antes de abrir vendas."
            ),
        },
    )

    # Contas criadas antes da cobrança existir não podem ser bloqueadas de
    # surpresa: entram com o mesmo período de teste de quem se cadastra hoje.
    fim = date.today() + timedelta(days=TRIAL_DIAS)
    for household in Household.objects.filter(assinaturas__isnull=True):
        Subscription.objects.create(
            household=household,
            tenant=household.tenant,
            plano=plano,
            status="trial",
            inicio=date.today(),
            trial_termina_em=fim,
            periodicidade="mensal",
        )


def remover(apps, schema_editor):
    apps.get_model("billing", "Subscription").objects.all().delete()
    apps.get_model("billing", "Plan").objects.filter(codigo="self_service").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0002_alter_subscription_options_and_more"),
        ("households", "0006_renomear_modo_lancamento"),
    ]

    operations = [migrations.RunPython(criar_plano_e_assinaturas, remover)]
