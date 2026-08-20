"""Cria os três planos comerciais do Batimento.

Apenas o Básico está disponível para assinatura. Intermediário e Consultor são
anunciados com preço definido e marcados como "em breve": mostrar o roteiro dá
contexto de valor ao Básico, desde que a interface não deixe ninguém tentar
assinar o que ainda não existe.

O plano antigo `self_service` vira o Básico — quem já tinha assinatura continua
apontando para um plano válido.
"""

from django.db import migrations


def criar_planos(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    Subscription = apps.get_model("billing", "Subscription")

    antigo = Plan.objects.filter(codigo="self_service").first()

    basico, _ = Plan.objects.update_or_create(
        codigo="basico",
        defaults={
            "nome": "Básico",
            "descricao": (
                "Organização financeira da família com fluxo de caixa, metas, "
                "simulador PJ x CLT, projeção de patrimônio, quitação de "
                "financiamentos e o conteúdo educacional mensal."
            ),
            "preco_mensal": "49.90",
            "preco_promocional": "39.90",
            "meses_promocionais": 6,
            "disponivel": True,
            "ativo": True,
            "ordem": 1,
            "recursos": [
                {"texto": "Fluxo de caixa com renda fixa e variável", "em_breve": False},
                {"texto": "Simulador PJ x CLT x autônomo por membro", "em_breve": False},
                {"texto": "Projeção de patrimônio de até 15 anos", "em_breve": False},
                {"texto": "Quitação de financiamentos (Price e SAC)", "em_breve": False},
                {"texto": "Metas da família e retrato financeiro em PDF", "em_breve": False},
                {"texto": "Conteúdo educacional mensal com dados do Banco Central", "em_breve": False},
            ],
        },
    )

    Plan.objects.update_or_create(
        codigo="intermediario",
        defaults={
            "nome": "Intermediário",
            "descricao": (
                "Tudo do Básico, mais análises geradas por inteligência artificial "
                "sobre os seus próprios dados da plataforma."
            ),
            "preco_mensal": "99.00",
            "preco_promocional": "80.90",
            "meses_promocionais": 3,
            "disponivel": False,
            "ativo": True,
            "ordem": 2,
            "recursos": [
                {"texto": "Tudo o que está no Básico", "em_breve": False},
                {"texto": "Análise dos seus dados gerada por IA", "em_breve": True},
                {"texto": "Leitura mensal do seu comportamento financeiro", "em_breve": True},
            ],
        },
    )

    Plan.objects.update_or_create(
        codigo="consultor",
        defaults={
            "nome": "Com consultor",
            "descricao": (
                "Acompanhamento humano de consultoria e contabilidade voltado à "
                "área médica, para o médico e sua família — ainda não para clínicas."
            ),
            "preco_mensal": "599.90",
            "preco_promocional": "499.90",
            "meses_promocionais": 6,
            "disponivel": False,
            "ativo": True,
            "ordem": 3,
            "recursos": [
                {"texto": "Tudo o que está no Intermediário", "em_breve": False},
                {"texto": "Consultor acompanhando seus números", "em_breve": True},
                {"texto": "Contabilidade voltada à área médica", "em_breve": True},
                {"texto": "Revisões periódicas com relatório de cada sessão", "em_breve": True},
            ],
        },
    )

    if antigo:
        Subscription.objects.filter(plano=antigo).update(plano=basico)
        antigo.delete()


def remover(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    Plan.objects.filter(codigo__in=["basico", "intermediario", "consultor"]).delete()


class Migration(migrations.Migration):
    dependencies = [("billing", "0004_alter_plan_options_plan_disponivel_and_more")]

    operations = [migrations.RunPython(criar_planos, remover)]
