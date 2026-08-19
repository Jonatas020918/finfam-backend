"""Contrato com o meio de pagamento.

A escolha do gateway ainda não foi feita, e o produto não pode ficar parado por
isso. Este módulo define a interface que qualquer provedor precisa cumprir e
entrega uma implementação manual, que já permite operar: cria a assinatura em
teste no cadastro e deixa a ativação ser feita no admin.

Quando Stripe ou Asaas entrarem, o trabalho é escrever uma classe aqui e apontar
`ASSINATURA_GATEWAY` no settings. Nenhuma regra de acesso muda — quem decide se
o cliente entra continua sendo `Subscription.da_acesso`.
"""

from abc import ABC, abstractmethod
from datetime import date, timedelta

from django.conf import settings
from django.utils.module_loading import import_string

from .models import Plan, StatusAssinatura, Subscription


class GatewayDePagamento(ABC):
    """O que qualquer provedor precisa saber fazer."""

    nome = "abstrato"

    @abstractmethod
    def criar_checkout(self, assinatura: Subscription, plano: Plan, url_retorno: str) -> str:
        """Devolve a URL para onde o cliente vai pagar."""

    @abstractmethod
    def criar_portal(self, assinatura: Subscription, url_retorno: str) -> str:
        """URL onde o cliente troca o cartão, vê faturas e cancela sozinho."""

    @abstractmethod
    def processar_evento(self, payload: dict) -> Subscription | None:
        """Aplica um webhook do provedor ao estado local da assinatura."""

    def cancelar(self, assinatura: Subscription) -> None:
        assinatura.cancelar()


class GatewayManual(GatewayDePagamento):
    """Sem provedor: a cobrança é combinada fora da plataforma.

    Serve para os primeiros clientes — cobra-se por Pix na mão e ativa-se a
    assinatura no admin. É honesto sobre o que não faz: pedir checkout ou portal
    levanta erro em vez de devolver uma URL falsa.
    """

    nome = "manual"

    def criar_checkout(self, assinatura, plano, url_retorno):
        raise NotImplementedError(
            "Nenhum gateway configurado. Ative a assinatura pelo admin enquanto "
            "a cobrança é feita manualmente."
        )

    def criar_portal(self, assinatura, url_retorno):
        raise NotImplementedError(
            "Portal do cliente exige um gateway configurado (Stripe, Asaas...)."
        )

    def processar_evento(self, payload):
        return None


def gateway_atual() -> GatewayDePagamento:
    """Instancia o gateway configurado. Manual é o padrão."""
    caminho = getattr(settings, "ASSINATURA_GATEWAY", None)
    if not caminho:
        return GatewayManual()
    return import_string(caminho)()


# --- Ciclo de vida ---------------------------------------------------------

def plano_padrao() -> Plan | None:
    """O plano em que um cadastro novo entra.

    É o primeiro assinável da vitrine, não um código fixo: o catálogo comercial
    muda com o tempo, e um código escrito no meio do código vira assinatura sem
    plano no dia em que aquele plano deixa de existir.
    """
    return Plan.objects.filter(ativo=True, disponivel=True).order_by("ordem").first()


def criar_assinatura_em_teste(household, plano: Plan | None = None) -> Subscription:
    """Todo cadastro nasce com período de teste.

    Sem isso, o cliente novo bateria em um bloqueio antes de ver o produto — e
    ninguém compra o que não experimentou.
    """
    dias = settings.ASSINATURA_TRIAL_DIAS
    plano = plano or plano_padrao()

    return Subscription.objects.create(
        household=household,
        tenant=household.tenant,
        plano=plano,
        status=StatusAssinatura.TRIAL,
        inicio=date.today(),
        trial_termina_em=date.today() + timedelta(days=dias),
    )


def assinatura_do_household(household) -> Subscription | None:
    """A assinatura que vale hoje: a mais recente do núcleo familiar."""
    return household.assinaturas.order_by("-criado_em").first()


def encerrar_periodos_vencidos() -> dict[str, int]:
    """Rotina diária: suspende quem passou do teste ou da carência.

    Roda no Celery Beat. É idempotente — passar duas vezes no mesmo dia não
    muda nada além do que já mudou.
    """
    hoje = date.today()

    trials = Subscription.objects.filter(
        status=StatusAssinatura.TRIAL, trial_termina_em__lt=hoje
    )
    carencias = Subscription.objects.filter(
        status=StatusAssinatura.INADIMPLENTE, carencia_ate__lt=hoje
    )

    total_trials = trials.count()
    total_carencias = carencias.count()

    for assinatura in list(trials) + list(carencias):
        assinatura.suspender()

    return {"trials_encerrados": total_trials, "carencias_encerradas": total_carencias}
