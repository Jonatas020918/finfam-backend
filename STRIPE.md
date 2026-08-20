# Configurar o Stripe

Do cadastro na Stripe até a primeira cobrança de verdade.

Enquanto isto não estiver feito, a plataforma roda com um gateway **simulado**:
o cliente clica em assinar, a tela responde, e nenhum centavo entra. É seguro
ficar assim — ninguém é cobrado errado — mas também não se vende nada.

---

## O princípio que organiza tudo

A promoção **não é um preço**. É um desconto temporário sobre o preço cheio.

No Stripe você cadastra um `Price` recorrente com o **valor cheio**, e um
`Coupon` que abate a diferença durante N meses. Passados os N meses, o cupom
para de valer sozinho e a fatura sobe para o cheio.

A alternativa — cadastrar o preço promocional e trocar o cliente de preço na
virada — exige lembrar de fazer isso para cada assinante, na data certa. É
onde se perde dinheiro e se ganha reclamação.

| Plano | `Price` (cheio) | `Coupon` (desconto) | Por |
|-------|-----------------|---------------------|-----|
| Básico | R$ 49,90/mês | R$ 10,00 | 6 meses |
| Intermediário | R$ 99,00/mês | R$ 18,10 | 3 meses |
| Com consultor | R$ 599,90/mês | R$ 100,00 | 6 meses |

Use desconto em **valor**, não em percentual: o percentual arredonda e a fatura
sai com centavos que não batem com o que você anunciou.

---

## Antes de tudo: modo de teste

O Stripe tem dois ambientes completamente separados — **Teste** e **Produção**.
Chaves, produtos, preços, cupons e webhooks não são compartilhados entre eles.

**Faça tudo em Teste primeiro.** Depois repita em Produção. Parece trabalho
dobrado, e é — mas é assim que você descobre um erro de configuração cobrando
um cartão falso, e não o cartão de um cliente.

O seletor fica no canto superior do painel.

---

## Passo 1 — Criar a conta

Em [stripe.com](https://stripe.com), crie a conta e escolha **Brasil** como
país. Isso define a moeda como BRL e habilita os meios de pagamento locais.

Para ativar o modo de produção, o Stripe pede dados da empresa (CNPJ costuma
ser exigido), conta bancária para repasse e um responsável. **Comece o cadastro
agora**, porque a análise leva de horas a alguns dias — e você pode ir montando
tudo em modo de teste enquanto ela corre.

---

## Passo 2 — Criar os produtos e preços

**Produtos → Adicionar produto.** Um para cada plano.

Para o Básico:

- **Nome:** `Batimento Básico`
- **Modelo de preço:** Recorrente
- **Valor:** `49,90`
- **Período:** Mensal
- **Moeda:** BRL

Salve e **copie o ID do preço** — começa com `price_`. Fica na página do
produto, ao lado do valor.

Repita para `Batimento Intermediário` (R$ 99,00) e `Batimento Com consultor`
(R$ 599,90).

> Cadastre os três agora, mesmo que só o Básico esteja à venda. Quando os
> outros forem liberados, é só marcar `disponível` no admin — sem mexer no
> Stripe de novo.

---

## Passo 3 — Criar os cupons

**Produtos → Cupons → Novo cupom.**

Para o Básico:

- **Tipo de desconto:** Valor fixo
- **Valor:** `10,00` BRL
- **Duração:** Vários meses (`repeating`)
- **Número de meses:** `6`

Copie o **ID do cupom**.

Repita: Intermediário `18,10` por `3` meses, Consultor `100,00` por `6` meses.

A duração precisa ser **repetida por N meses**. Se ficar "para sempre"
(`forever`), você dá desconto vitalício sem perceber. Se ficar "uma vez"
(`once`), o cliente paga promocional no primeiro mês e cheio no segundo — e
reclama, com razão.

---

## Passo 4 — Registrar os IDs no admin

Abra `https://SEU_DOMINIO/admin/` → **Billing → Planos**.

Em cada plano, preencha:

| Campo | Valor |
|-------|-------|
| `stripe_price_id` | o `price_...` do passo 2 |
| `stripe_coupon_id` | o ID do cupom do passo 3 |

São esses dois campos que ligam seu catálogo ao do Stripe. Sem o `price_id`, a
cobrança falha — e falha com uma mensagem clara, porque o código verifica isso
antes de chamar a API.

---

## Passo 5 — Pegar as chaves

**Desenvolvedores → Chaves de API.**

| Chave | Onde vai no `.env` | Formato |
|-------|--------------------|---------|
| Chave publicável | `STRIPE_PUBLIC_KEY` | `pk_test_...` / `pk_live_...` |
| Chave secreta | `STRIPE_SECRET_KEY` | `sk_test_...` / `sk_live_...` |

A chave secreta aparece uma vez. Se perder, gere outra — não existe "ver de
novo".

**Ela nunca vai para o Git.** Só para o `.env` do servidor, que está no
`.gitignore`.

---

## Passo 6 — Webhook

É por aqui que o Stripe avisa a plataforma que um pagamento aconteceu. Sem
webhook, o cliente paga e **não recebe acesso** — o dinheiro entra e a conta
continua bloqueada.

**Este passo precisa do domínio no ar com HTTPS.** É o único que não dá para
adiantar.

**Desenvolvedores → Webhooks → Adicionar endpoint.**

- **URL:** `https://SEU_DOMINIO/api/assinatura/webhook/`
- **Eventos a escutar** — exatamente estes quatro:

```
checkout.session.completed
invoice.payment_succeeded
invoice.payment_failed
customer.subscription.deleted
```

Não marque "todos os eventos". O código ignora o resto de propósito, e uma
enxurrada de eventos irrelevantes só polui o log e o painel.

Depois de salvar, copie o **Signing secret** (`whsec_...`) para
`STRIPE_WEBHOOK_SECRET`.

Esse segredo é o que prova que o evento veio mesmo do Stripe. Sem ele, a rota
recusa tudo — e isso é proposital: sem verificação de assinatura, aquele
endereço seria um botão público de liberar acesso pago.

---

## Passo 7 — Ligar o gateway real

No `.env` do servidor:

```
ASSINATURA_GATEWAY=apps.billing.gateways_stripe.GatewayStripe
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLIC_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

A única mudança é a primeira linha: sai `GatewayStripeMock`, entra
`GatewayStripe`. O resto do código é o mesmo — o mock herda da classe real e
só substitui as três chamadas de rede.

Suba de novo:

```
docker compose -f docker-compose.prod.yml up -d
```

Confira que o aviso do gateway simulado sumiu:

```
docker compose -f docker-compose.prod.yml run --rm api python manage.py check --deploy
```

---

## Passo 8 — Testar o ciclo inteiro

Ainda em **modo de teste**. Crie uma conta na plataforma e assine o Básico.

Cartões que o Stripe aceita em teste:

| Número | O que acontece |
|--------|----------------|
| `4242 4242 4242 4242` | Aprova |
| `4000 0000 0000 0002` | Recusa |
| `4000 0025 0000 3155` | Pede autenticação (3-D Secure) |

Data de validade: qualquer uma futura. CVC: qualquer três dígitos.

**O que verificar depois de pagar:**

1. A tela de assinatura mostra "ativa"
2. No admin, a assinatura tem `gateway=stripe` e um `customer` preenchido
3. `promocao_ate` está seis meses à frente
4. No painel do Stripe, em Webhooks, os eventos aparecem com resposta `200`

Se o evento aparecer com erro, clique nele: o Stripe mostra o que a sua API
respondeu. É o melhor lugar para diagnosticar.

**Teste também a recusa.** Assine com o cartão `4000 0000 0000 0002` e confirme
que a conta entra em carência em vez de ser cortada na hora — é o
comportamento certo, porque cartão vencido é o motivo mais comum de falha.

---

## Passo 9 — Produção

Só depois que o ciclo de teste inteiro passar:

1. Troque o painel para **modo de produção**
2. **Refaça os passos 2, 3 e 6** — produtos, preços, cupons e webhook não são
   copiados do teste
3. Atualize os `stripe_price_id` e `stripe_coupon_id` no admin com os novos IDs
4. Troque as três chaves no `.env` para as versões `live`
5. Suba de novo
6. **Faça uma assinatura real, com o seu cartão**, e depois cancele e estorne

O passo 6 parece exagero e não é. É a única forma de saber que o dinheiro
chega na sua conta bancária de verdade.

---

## Sobre meios de pagamento

O Stripe no Brasil aceita **cartão de crédito, Pix e boleto**. Para assinatura
recorrente, cartão é o único que renova sozinho — Pix e boleto exigem que o
cliente pague de novo a cada ciclo.

Comece só com cartão. É o que o código trata hoje, e o que funciona sem
ninguém precisar lembrar de pagar.

---

## O que ainda falta para vender legalmente

O Stripe resolve a cobrança. Não resolve:

- **Nota fiscal.** Cobrança e NFS-e são coisas separadas. Os dados fiscais já
  são coletados na plataforma, mas a emissão ainda é manual.
- **LGPD.** Política de privacidade, termos com aceite registrado, exclusão de
  conta e exportação de dados.

Nenhum dos dois é configuração de Stripe — mas os dois são exigência para
cobrar de um cliente no Brasil.

---

## Se algo der errado

**"O plano X ainda não está disponível para assinatura"** — o plano está com
`disponivel=False` no admin. É o esperado para Intermediário e Consultor.

**"Plano sem stripe_price_id"** — falta preencher o campo no admin. A mensagem
é essa mesmo, de propósito: o erro que o Stripe devolveria não diria qual plano
ficou pela metade.

**Pagou e não liberou o acesso** — é o webhook. Veja em Desenvolvedores →
Webhooks se os eventos estão chegando e com qual resposta.

**Webhook respondendo 503** — falta `STRIPE_WEBHOOK_SECRET` no `.env`.

**Webhook respondendo 400** — o segredo está errado, ou é o do outro ambiente
(teste em produção, ou vice-versa).
