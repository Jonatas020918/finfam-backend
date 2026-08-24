"""Tira o recorte médico do catálogo de planos.

A generalização do produto passou pelo código e pelos rótulos, mas a vitrine
de planos mora no banco — e continuou dizendo "voltado à área médica, para o
médico e sua família". Quem chegasse de outra profissão leria, na tela de
preço, que o produto não é para ela.

Só texto: preço, cupom e identificadores do Stripe não são tocados aqui.
"""

from django.db import migrations

DESCRICAO_NOVA = (
    "Acompanhamento humano de consultoria e contabilidade para você e sua "
    "família — ainda não para empresas com equipe."
)
DESCRICAO_ANTIGA = (
    "Acompanhamento humano de consultoria e contabilidade voltado à área "
    "médica, para o médico e sua família — ainda não para clínicas."
)

RECURSO_NOVO = "Contabilidade para autônomo e PJ"
RECURSO_ANTIGO = "Contabilidade voltada à área médica"


def _trocar_recurso(plano, de, para):
    plano.recursos = [
        {**r, "texto": para} if r.get("texto") == de else r for r in (plano.recursos or [])
    ]


def generalizar(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    consultor = Plan.objects.filter(codigo="consultor").first()
    if consultor is None:
        return
    consultor.descricao = DESCRICAO_NOVA
    _trocar_recurso(consultor, RECURSO_ANTIGO, RECURSO_NOVO)
    consultor.save(update_fields=["descricao", "recursos"])


def reverter(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    consultor = Plan.objects.filter(codigo="consultor").first()
    if consultor is None:
        return
    consultor.descricao = DESCRICAO_ANTIGA
    _trocar_recurso(consultor, RECURSO_NOVO, RECURSO_ANTIGO)
    consultor.save(update_fields=["descricao", "recursos"])


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0008_subscription_trial_libera_acesso'),
    ]

    operations = [
        migrations.RunPython(generalizar, reverter),
    ]
