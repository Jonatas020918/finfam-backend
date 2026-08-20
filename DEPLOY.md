# Subir o Batimento em produção

Do primeiro `ssh` até o site no ar com HTTPS. Escrito para um VPS da Hostinger
com Ubuntu LTS, mas serve para qualquer servidor Linux com Docker.

Leva de 40 a 60 minutos na primeira vez, e a maior parte é espera de
compilação.

**Antes de começar, uma coisa precisa estar pronta:** o DNS apontando para o
IP do servidor. O certificado HTTPS é emitido pela Let's Encrypt, que confirma
a posse do domínio acessando-o por HTTP. Se o DNS ainda não propagou, a
emissão falha e você fica olhando para um erro que não explica isso.

---

## Passo 0 — DNS (faça primeiro e vá tomar um café)

No hPanel da Hostinger → **Domínios → batimento.com.br → DNS**:

| Tipo | Nome | Valor |
|------|------|-------|
| A | `@` | IP do seu VPS |
| A | `www` | IP do seu VPS |

A propagação leva de minutos a algumas horas. Confira de outra máquina:

```
nslookup batimento.com.br 8.8.8.8
```

Quando responder com o IP do VPS, siga. Enquanto responder "não encontrado",
não adianta continuar — o passo 7 vai falhar.

---

## Passo 1 — Primeiro acesso

```
ssh root@SEU_IP
```

Atualize o sistema:

```
apt update && apt upgrade -y
```

### Um usuário que não é root

Trabalhar como root o tempo todo significa que qualquer comando errado é
irreversível. Crie um usuário e dê a ele acesso ao Docker:

```
adduser batimento
usermod -aG sudo batimento
rsync --archive --chown=batimento:batimento ~/.ssh /home/batimento
```

A terceira linha copia sua chave SSH para o novo usuário — sem ela você não
consegue entrar com ele.

Saia e entre de novo como o novo usuário:

```
ssh batimento@SEU_IP
```

### Firewall

```
sudo ufw allow OpenSSH && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw --force enable
```

Postgres e Redis não aparecem aqui de propósito: o compose de produção não
publica as portas deles, então só são alcançáveis de dentro da rede do Docker.
Banco exposto na internet é o jeito mais rápido de perder a base.

---

## Passo 2 — Swap (importante no plano de 1 núcleo)

A compilação do frontend é a parte mais pesada de todo o processo e roda no
servidor. Com 4 GB de RAM ela costuma passar, mas o swap evita que o build
morra no meio por falta de memória:

```
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
```

Para sobreviver a um reinício:

```
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## Passo 3 — Docker

```
curl -fsSL https://get.docker.com | sudo sh
```

Deixe seu usuário usar o Docker sem `sudo`:

```
sudo usermod -aG docker $USER
```

**Saia e entre de novo** — a mudança de grupo só vale em sessão nova. Confira:

```
docker run --rm hello-world
```

---

## Passo 4 — Trazer o código

Os dois repositórios precisam ficar **lado a lado**: o compose de produção
compila o frontend a partir de `../finfam-frontend`.

```
mkdir -p ~/batimento && cd ~/batimento
```

```
git clone https://github.com/Jonatas020918/finfam-backend.git
```

```
git clone https://github.com/Jonatas020918/finfam-frontend.git
```

Se os repositórios forem privados, o `git` vai pedir usuário e senha — e o
GitHub não aceita mais senha de conta. Gere um *personal access token* em
github.com → Settings → Developer settings → Tokens, e use o token no lugar da
senha.

A estrutura final tem que ser esta:

```
~/batimento/
├── finfam-backend/     ← todos os comandos rodam daqui
└── finfam-frontend/
```

---

## Passo 5 — Configurar o `.env`

```
cd ~/batimento/finfam-backend && cp .env.producao.exemplo .env
```

Gere a chave secreta:

```
docker run --rm python:3.13-slim python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Gere a senha do banco:

```
openssl rand -base64 24
```

Agora edite:

```
nano .env
```

O arquivo explica, variável por variável, onde buscar cada valor. O mínimo
para subir:

| Variável | De onde vem |
|----------|-------------|
| `SECRET_KEY` | do comando acima |
| `POSTGRES_PASSWORD` | do comando acima |
| `DOMINIO` | `batimento.com.br` |
| `EMAIL_ACME` | seu e-mail pessoal (avisos da Let's Encrypt) |
| `EMAIL_HOST_USER` | hPanel → E-mails → Contas de e-mail |
| `EMAIL_HOST_PASSWORD` | a senha daquele mailbox |

`ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` e
`FRONTEND_URL` já vêm preenchidos com `batimento.com.br`.

Deixe o `ASSINATURA_GATEWAY` no mock por enquanto. Ninguém consegue pagar, o
que significa que ninguém é cobrado errado no primeiro dia no ar.

---

## Passo 6 — Validar antes de subir

Este passo existe para você **não descobrir o problema com o site no ar**:

```
docker compose -f docker-compose.prod.yml run --rm api python manage.py check --deploy
```

Ele trava se o e-mail estiver caindo no console, se `ALLOWED_HOSTS` tiver
curinga, se a criptografia do SMTP estiver incoerente ou se os estáticos não
tiverem sido coletados. Cada erro vem com a explicação do que fazer.

Um aviso sobre o gateway simulado é esperado agora.

Prove que o e-mail sai da máquina:

```
docker compose -f docker-compose.prod.yml run --rm api python manage.py testar_email voce@gmail.com
```

Use um endereço que você consiga abrir. Se não chegar, confira o spam — e se
estiver no spam, faltam os registros SPF, DKIM e DMARC do passo 10.

---

## Passo 7 — Subir

```
docker compose -f docker-compose.prod.yml up -d --build
```

A primeira vez demora: compila a imagem do Python, instala as dependências e
compila o Angular. **De 10 a 20 minutos** num VPS de 1 núcleo.

Acompanhe:

```
docker compose -f docker-compose.prod.yml logs -f
```

O que você quer ver:

- `caddy` obtendo o certificado (`certificate obtained successfully`)
- `api` rodando as migrações e depois `Booting worker`
- `beat` anunciando o agendamento

Se o Caddy reclamar do certificado, quase sempre é o DNS ainda não propagado.
Ele tenta de novo sozinho a cada poucos minutos.

---

## Passo 8 — Criar seu acesso ao admin

```
docker compose -f docker-compose.prod.yml exec api python manage.py createsuperuser
```

É por aqui que você vai cadastrar os preços do Stripe quando for cobrar.

---

## Passo 9 — Conferir que está tudo de pé

Abra no navegador:

- `https://batimento.com.br` — a landing, com cadeado
- `https://batimento.com.br/admin/` — o admin, **com estilo** (se aparecer sem
  CSS, os estáticos não foram coletados)
- `https://batimento.com.br/api/saude/` — deve responder `{"status":"ok"}`

E faça o teste que importa: **crie uma conta de verdade** pela tela de
cadastro, entre, cadastre uma receita fixa e veja se o painel reflete. É o
caminho que seu primeiro cliente vai percorrer.

Confira também que o HTTP redireciona para HTTPS:

```
curl -I http://batimento.com.br
```

---

## Passo 10 — E-mail que não cai no spam

No hPanel → **Domínios → DNS**, confirme que existem:

| Tipo | Nome | Valor |
|------|------|-------|
| MX | `@` | o que a Hostinger indicar |
| TXT | `@` | `v=spf1 include:_spf.mail.hostinger.com ~all` |
| TXT | (o que o hPanel gerar) | DKIM, em E-mails → Configurações de DNS |
| TXT | `_dmarc` | `v=DMARC1; p=none; rua=mailto:voce@batimento.com.br` |

Comece o DMARC com `p=none`: ele só relata, sem descartar nada. Depois de
algumas semanas de relatório limpo, endureça para `p=quarantine`.

Sem esses registros, o e-mail sai do servidor e cai no spam do cliente — que,
do lado dele, é idêntico a não ter chegado.

---

## Passo 11 — Backup automático

```
chmod +x scripts/backup.sh scripts/restaurar.sh
```

```
crontab -e
```

Acrescente:

```
0 3 * * * cd /home/batimento/batimento/finfam-backend && ./scripts/backup.sh >> /var/log/batimento-backup.log 2>&1
```

**E agora faça o que quase ninguém faz:** teste a restauração. Backup que
nunca foi restaurado não é backup, é esperança.

```
./scripts/backup.sh
```

```
docker compose -f docker-compose.prod.yml exec db createdb -U batimento teste_restauracao
```

```
BANCO=teste_restauracao ./scripts/restaurar.sh backups/o_arquivo_gerado.sql.gz
```

```
docker compose -f docker-compose.prod.yml exec db dropdb -U batimento teste_restauracao
```

---

## Atualizar depois

```
cd ~/batimento/finfam-backend && git pull && cd ../finfam-frontend && git pull && cd ../finfam-backend
```

```
docker compose -f docker-compose.prod.yml up -d --build
```

As migrações rodam sozinhas na subida da `api`.

---

## Quando for começar a cobrar

1. Crie a conta no Stripe
2. Em Produtos, crie um `Price` recorrente mensal com o **valor cheio** de cada
   plano (49,90 / 99,00 / 599,90)
3. Em Cupons, crie um desconto com duração **repetida** por N meses, cobrindo a
   diferença até o preço promocional
4. No admin do Batimento → Billing → Plans, preencha `stripe_price_id` e
   `stripe_coupon_id` de cada plano
5. Em Webhooks, adicione `https://batimento.com.br/api/assinatura/webhook/` e
   copie o *signing secret*
6. No `.env`, troque `ASSINATURA_GATEWAY` para `...GatewayStripe` e preencha as
   três chaves
7. Suba de novo e **teste o ciclo inteiro com cartão de teste** antes de
   anunciar

---

## Ainda pendente para vender legalmente

O parecer de QA aponta itens que não são configuração e que este guia não
resolve:

- **LGPD**: política de privacidade, termos com aceite registrado, exclusão de
  conta e exportação de dados
- **Observabilidade**: Sentry, para saber de um erro antes de o cliente
  reclamar
- **Validação jurídica** do conteúdo educacional

Subir agora com o gateway simulado é seguro: a plataforma fica no ar, você
valida a infraestrutura, e ninguém consegue ser cobrado. Vender é o passo
seguinte.

---

## Se algo der errado

**Ver o que aconteceu:**

```
docker compose -f docker-compose.prod.yml logs --tail 100 api
```

**Estado dos contêineres:**

```
docker compose -f docker-compose.prod.yml ps
```

**Site não abre, ou fica redirecionando sem parar:** quase sempre é o
certificado que não saiu. Veja `logs caddy` e confirme o DNS.

**Admin sem estilo:** os estáticos não foram coletados. Reconstrua a imagem
com `up -d --build`.

**"CSRF verification failed" ao entrar no admin:** falta o domínio em
`CSRF_TRUSTED_ORIGINS`.

**Build do frontend morre sem mensagem clara:** falta memória. Confirme o swap
do passo 2 com `free -h`.
