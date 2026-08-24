"""Integração com o Stripe.

Duas classes moram aqui:

  GatewayStripe      — a integração de verdade, contra a API do Stripe.
  GatewayStripeMock  — a mesma coisa, com as três chamadas de rede substituídas
                       por simulação local.

**O mock é temporário.** Ele existe porque a conta do Stripe ainda não foi
configurada, e o produto não pode ficar sem fluxo de assinatura por causa disso.
Reverter para as chamadas reais é uma linha no .env:

    ASSINATURA_GATEWAY=apps.billing.gateways_stripe.GatewayStripe
    STRIPE_SECRET_KEY=sk_live_...
    STRIPE_WEBHOOK_SECRET=whsec_...

O mock **herda** da classe real de propósito: toda a lógica de tradução entre
eventos do Stripe e o estado local é exercitada igual nos dois. Só o que sai
pela rede é falso — então quando a chave chegar, o caminho já foi percorrido.

Sobre a promoção: o preço cheio é o `Price` recorrente no Stripe, e os meses
promocionais entram como `Coupon` com `duration=repeating`. Isso mantém uma
única assinatura no Stripe, com o desconto caindo sozinho no mês certo — bem
mais confiável que trocar o cliente de preço na virada.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings

from .gateways import GatewayDePagamento
from .models import Plan, Subscription


class GatewayStripe(GatewayDePagamento):
    nome = "stripe"

    # --- Acesso ao SDK ------------------------------------------------------

    def _stripe(self):
        """Importa e configura o SDK sob demanda.

        Import tardio para o projeto rodar sem a biblioteca instalada enquanto
        o mock estiver no ar.
        """
        import stripe

        stripe.api_key = settings.STRIPE_SECRET_KEY
        return stripe

    # --- Chamadas de rede: são estes três pontos que o mock substitui -------

    def _criar_sessao_checkout(self, parametros: dict) -> dict:
        # Falha aqui é melhor que falha no Stripe: sem o Price cadastrado, a
        # mensagem que voltaria de lá não diz qual plano ficou pela metade.
        if not parametros["line_items"][0].get("price"):
            raise ValueError(
                "Plano sem stripe_price_id. Cadastre o Price no Stripe e preencha "
                "o campo no admin antes de abrir a cobrança."
            )
        return self._stripe().checkout.Session.create(**parametros)

    def _criar_sessao_portal(self, parametros: dict) -> dict:
        return self._stripe().billing_portal.Session.create(**parametros)

    def _buscar_cupom(self, codigo: str) -> dict | None:
        """Promotion Code ativo com este código, se existir.

        Não é o `Coupon` em si — é o código que a pessoa digita (o cupom
        criado à mão no Stripe para um cliente específico precisa de um
        Promotion Code apontando para ele, não só do Coupon isolado).
        """
        resultado = self._stripe().PromotionCode.list(code=codigo, active=True, limit=1)
        return resultado["data"][0] if resultado["data"] else None

    def _verificar_assinatura_do_evento(self, corpo: bytes, cabecalho: str) -> dict:
        """Sem verificar a assinatura, qualquer um poderia liberar acesso."""
        return self._stripe().Webhook.construct_event(
            corpo, cabecalho, settings.STRIPE_WEBHOOK_SECRET
        )

    def _buscar_assinatura(self, assinatura_id: str) -> dict | None:
        """A assinatura como o Stripe a vê — precisamos dela pelo `trial_end`.

        O evento `checkout.session.completed` não traz quando o teste acaba, e
        essa é justamente a data que o cliente precisa ver: o dia em que o
        cartão vai ser cobrado pela primeira vez. Vale uma chamada a mais.
        """
        try:
            return self._stripe().Subscription.retrieve(assinatura_id)
        except Exception:
            # O acesso não pode depender desta consulta: se ela falhar, a
            # assinatura ainda é ativada e a tela só fica sem a data.
            return None

    # --- Contrato -----------------------------------------------------------

    def criar_checkout(
        self,
        assinatura: Subscription,
        plano: Plan,
        url_retorno: str,
        cupom: str | None = None,
    ) -> str:
        if not plano.disponivel:
            raise ValueError(f"O plano {plano.nome} ainda não está disponível para assinatura.")

        parametros = {
            "mode": "subscription",
            "line_items": [{"price": plano.stripe_price_id, "quantity": 1}],
            "success_url": f"{url_retorno}?assinatura=ok",
            "cancel_url": f"{url_retorno}?assinatura=cancelado",
            "locale": "pt-BR",
            "client_reference_id": str(assinatura.id),
            "subscription_data": {"metadata": {"assinatura_id": str(assinatura.id)}},
        }
        if assinatura.gateway_customer_id:
            parametros["customer"] = assinatura.gateway_customer_id

        if cupom:
            # Cupom avulso (prospecção de um cliente específico) substitui a
            # promoção padrão — o Stripe não deixa combinar desconto
            # automático com um código digitado na mesma sessão, e o cupom
            # que a pessoa trouxe é o que vale.
            encontrado = self._buscar_cupom(cupom)
            if encontrado is None:
                raise ValueError("Cupom inválido ou expirado.")
            parametros["discounts"] = [{"promotion_code": encontrado["id"]}]
        elif plano.em_promocao and plano.stripe_coupon_id:
            # A promoção padrão entra como cupom: some sozinha no mês certo.
            parametros["discounts"] = [{"coupon": plano.stripe_coupon_id}]

        sessao = self._criar_sessao_checkout(parametros)
        return sessao["url"]

    def criar_portal(self, assinatura: Subscription, url_retorno: str) -> str:
        if not assinatura.gateway_customer_id:
            raise ValueError("Assinatura ainda não tem cliente no Stripe.")

        sessao = self._criar_sessao_portal(
            {"customer": assinatura.gateway_customer_id, "return_url": url_retorno}
        )
        return sessao["url"]

    def processar_evento(self, payload: dict) -> Subscription | None:
        """Traduz um evento do Stripe para o estado local.

        Só quatro eventos importam para o acesso — os demais são ignorados de
        propósito, para o webhook não virar um depósito de regras.
        """
        tipo = payload.get("type")
        objeto = payload.get("data", {}).get("object", {})

        assinatura = self._localizar(objeto)
        if assinatura is None:
            return None

        if tipo == "checkout.session.completed":
            assinatura.gateway = self.nome
            assinatura.gateway_customer_id = objeto.get("customer") or ""
            assinatura.gateway_subscription_id = objeto.get("subscription") or ""
            assinatura.save(
                update_fields=[
                    "gateway", "gateway_customer_id", "gateway_subscription_id", "atualizado_em"
                ]
            )
            # Com teste configurado no Price, nada é cobrado hoje: a primeira
            # fatura sai quando o teste acaba. É essa data que a tela mostra
            # como "próxima cobrança" — e é dela que a promoção passa a
            # contar, para os meses de desconto não serem gastos de graça
            # durante o teste.
            fim_do_teste = self._fim_do_teste(assinatura.gateway_subscription_id)
            self._marcar_promocao(assinatura, a_partir_de=fim_do_teste)
            assinatura.ativar(proxima_cobranca=fim_do_teste)

        elif tipo == "invoice.payment_succeeded":
            assinatura.ativar(proxima_cobranca=self._data(objeto.get("period_end")))

        elif tipo == "invoice.payment_failed":
            # Carência em vez de corte: o motivo mais comum é cartão vencido.
            assinatura.iniciar_carencia()

        elif tipo == "customer.subscription.deleted":
            assinatura.cancelar()

        return assinatura

    # --- Apoio --------------------------------------------------------------

    def _localizar(self, objeto: dict) -> Subscription | None:
        """Acha a assinatura local pelo id que enviamos ao criar o checkout."""
        referencia = objeto.get("client_reference_id") or (objeto.get("metadata") or {}).get(
            "assinatura_id"
        )
        if referencia:
            return Subscription.objects.filter(pk=referencia).first()

        for campo, valor in (
            ("gateway_subscription_id", objeto.get("subscription") or objeto.get("id")),
            ("gateway_customer_id", objeto.get("customer")),
        ):
            if valor:
                encontrada = Subscription.objects.filter(**{campo: valor}).first()
                if encontrada:
                    return encontrada
        return None

    def _fim_do_teste(self, assinatura_id: str) -> date | None:
        """Quando o teste do Stripe acaba — ou seja, o dia da primeira cobrança."""
        if not assinatura_id:
            return None
        remota = self._buscar_assinatura(assinatura_id)
        if not remota:
            return None
        return self._data(remota.get("trial_end"))

    def _marcar_promocao(
        self, assinatura: Subscription, a_partir_de: date | None = None
    ) -> None:
        """Até quando vale o preço promocional.

        Conta do fim do teste, não da assinatura: durante o teste não há
        cobrança, então um mês de desconto gasto ali seria um mês que o
        cliente pagou de propaganda e não recebeu.
        """
        plano = assinatura.plano
        if not plano or not plano.em_promocao:
            return
        inicio = a_partir_de or date.today()
        assinatura.promocao_ate = inicio + timedelta(days=30 * plano.meses_promocionais)
        assinatura.save(update_fields=["promocao_ate", "atualizado_em"])

    @staticmethod
    def _data(timestamp) -> date | None:
        if not timestamp:
            return None
        return date.fromtimestamp(int(timestamp))


class GatewayStripeMock(GatewayStripe):
    """TEMPORÁRIO — simula o Stripe enquanto a conta não está configurada.

    Substitui apenas as três chamadas de rede da classe acima. Todo o resto
    (montagem dos parâmetros, tradução de eventos, transições de estado) roda
    exatamente como rodará em produção.

    Para remover: apague esta classe e aponte ASSINATURA_GATEWAY para
    GatewayStripe. Nada mais no projeto referencia o mock.
    """

    nome = "stripe"  # o mesmo nome: o estado gravado já é o definitivo

    #: Sessões simuladas, para inspeção em teste e desenvolvimento.
    sessoes: list[dict] = []

    def _criar_sessao_checkout(self, parametros: dict) -> dict:
        GatewayStripeMock.sessoes.append(parametros)
        referencia = parametros.get("client_reference_id", "sem-referencia")
        # A URL aponta para a própria aplicação: o clique leva a uma tela que
        # explica a simulação, em vez de a um domínio que não existe.
        retorno = parametros["success_url"]
        return {
            "id": f"cs_mock_{referencia[:8]}",
            "url": f"{retorno}&simulado=1",
            "customer": f"cus_mock_{referencia[:8]}",
            "subscription": f"sub_mock_{referencia[:8]}",
        }

    def _criar_sessao_portal(self, parametros: dict) -> dict:
        return {"url": f"{parametros['return_url']}?portal=simulado"}

    def _buscar_assinatura(self, assinatura_id: str) -> dict | None:
        """Simula o teste configurado no Price: começa hoje, dura o previsto."""
        from datetime import datetime, time

        fim = datetime.combine(
            date.today() + timedelta(days=settings.ASSINATURA_TRIAL_DIAS), time.min
        )
        return {"id": assinatura_id, "status": "trialing", "trial_end": int(fim.timestamp())}

    def _buscar_cupom(self, codigo: str) -> dict | None:
        # "invalido" no código simula um cupom inexistente/expirado, para dar
        # para testar os dois caminhos sem conta no Stripe.
        if not codigo or "invalido" in codigo.lower():
            return None
        return {"id": f"promo_mock_{codigo}"}

    def _verificar_assinatura_do_evento(self, corpo: bytes, cabecalho: str) -> dict:
        """Sem chave, não há o que verificar — o corpo é aceito como veio.

        É seguro apenas porque o webhook do mock não roda em produção: a rota
        recusa eventos quando não há STRIPE_WEBHOOK_SECRET configurado.
        """
        import json

        return json.loads(corpo or b"{}")

    def confirmar_pagamento(self, assinatura: Subscription) -> Subscription:
        """Atalho de desenvolvimento: simula o retorno do checkout pago.

        Existe para dar para percorrer o fluxo inteiro sem conta no Stripe.
        Some junto com o mock.
        """
        return self.processar_evento(
            {
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "client_reference_id": str(assinatura.id),
                        "customer": f"cus_mock_{str(assinatura.id)[:8]}",
                        "subscription": f"sub_mock_{str(assinatura.id)[:8]}",
                    }
                },
            }
        )


def valor_cobrado_hoje(plano: Plan) -> Decimal:
    """Quanto sai na primeira fatura, considerando a promoção."""
    return Decimal(plano.preco_de_entrada)
