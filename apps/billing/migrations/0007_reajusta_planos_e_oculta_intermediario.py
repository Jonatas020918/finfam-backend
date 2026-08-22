"""Reajuste comercial: 2 planos na vitrine, preços revistos, anual no Básico.

O Intermediário nunca teve nenhuma entrega real — as duas coisas que o
diferenciavam do Básico ("análise por IA", "leitura mensal do comportamento")
sempre estiveram marcadas como `em_breve`. Mostrar um plano pago que entrega
exatamente o mesmo que o de baixo é pior do que não mostrá-lo: ele fica
oculto (`ativo=False`) até ter pelo menos um recurso de verdade — os dados
continuam no banco, prontos para reativar.

Básico e Com consultor sobem de preço porque o valor entregue (e, no caso do
consultor, o custo real de entregar contabilidade médica + acompanhamento
pessoal) não cabia nos valores anteriores. Como o Consultor ainda está
"em breve", ninguém paga o preço antigo hoje — é o momento mais barato para
corrigir a âncora.

O Básico ganha preço anual (R$ 79,90 × 10 = R$ 799,00, o equivalente a dois
meses grátis). Isso só popula o dado: o checkout ainda só sabe cobrar mensal
— vender anual de verdade é tarefa futura, não desta migração.
"""

from django.db import migrations


def reajustar(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")

    Plan.objects.filter(codigo="basico").update(
        preco_mensal="79.90",
        preco_promocional="59.90",
        preco_anual="799.00",
    )
    Plan.objects.filter(codigo="intermediario").update(ativo=False)

    consultor = Plan.objects.get(codigo="consultor")
    consultor.preco_mensal = "899.90"
    consultor.preco_promocional = "699.90"
    # Com o Intermediário fora da vitrine, "tudo o que está nele" vira uma
    # referência a um plano que ninguém mais vê — o predecessor visível agora
    # é o Básico.
    consultor.recursos = [
        {"texto": "Tudo o que está no Básico", "em_breve": False},
        *consultor.recursos[1:],
    ]
    consultor.save(update_fields=["preco_mensal", "preco_promocional", "recursos"])


def reverter(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")

    Plan.objects.filter(codigo="basico").update(
        preco_mensal="49.90",
        preco_promocional="39.90",
        preco_anual=None,
    )
    Plan.objects.filter(codigo="intermediario").update(ativo=True)

    consultor = Plan.objects.get(codigo="consultor")
    consultor.preco_mensal = "599.90"
    consultor.preco_promocional = "499.90"
    consultor.recursos = [
        {"texto": "Tudo o que está no Intermediário", "em_breve": False},
        *consultor.recursos[1:],
    ]
    consultor.save(update_fields=["preco_mensal", "preco_promocional", "recursos"])


class Migration(migrations.Migration):
    dependencies = [("billing", "0006_assinaturas_sem_plano")]

    operations = [migrations.RunPython(reajustar, reverter)]
