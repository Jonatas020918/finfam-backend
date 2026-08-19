"""Devolve um plano às assinaturas que ficaram sem nenhum.

A 0005 apagou o plano `self_service`, mas o cadastro continuava procurando por
ele: todo cliente que entrou entre as duas migrações ficou com assinatura sem
plano — em teste, com acesso, e sem saber para onde vai quando o teste acabar.

Aqui só o vazio é preenchido. Quem já escolheu um plano permanece nele.
"""

from django.db import migrations


def vincular_ao_basico(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    Subscription = apps.get_model("billing", "Subscription")

    padrao = (
        Plan.objects.filter(ativo=True, disponivel=True).order_by("ordem").first()
        or Plan.objects.filter(codigo="basico").first()
    )
    if padrao:
        Subscription.objects.filter(plano__isnull=True).update(plano=padrao)


class Migration(migrations.Migration):
    dependencies = [("billing", "0005_tres_planos")]

    operations = [migrations.RunPython(vincular_ao_basico, migrations.RunPython.noop)]
