"""Converte os valores antigos de `modo_lancamento`.

'media'/'mensal' descreviam a implementação (como o número era obtido);
'fixa'/'variavel' descrevem o que o usuário decide (o valor muda ou não todo
mês). Como a interface passou a falar nesses termos, o dado acompanha.
"""

from django.db import migrations

DE_PARA = {"media": "fixa", "mensal": "variavel"}


def para_frente(apps, schema_editor):
    IncomeSource = apps.get_model("households", "IncomeSource")
    for antigo, novo in DE_PARA.items():
        IncomeSource.objects.filter(modo_lancamento=antigo).update(modo_lancamento=novo)


def para_tras(apps, schema_editor):
    IncomeSource = apps.get_model("households", "IncomeSource")
    for antigo, novo in DE_PARA.items():
        IncomeSource.objects.filter(modo_lancamento=novo).update(modo_lancamento=antigo)


class Migration(migrations.Migration):
    dependencies = [("households", "0005_alter_incomesource_modo_lancamento")]

    operations = [migrations.RunPython(para_frente, para_tras)]
