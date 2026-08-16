# Roadmap de desenvolvimento — Plataforma FinFam

Plano de execução da especificação `Documentacao_Plataforma_Consultoria_Medicos.docx`
(v2.0) até o MVP da **Fase 1 — Self-Service**.

---

## 1. Por que backend primeiro

A decisão de arquitetura é **backend-first, com contrato de API como entregável de
cada sprint**. Os motivos, nesta ordem:

1. **O valor do produto está no cálculo, não na tela.** Simulador PJ x CLT,
   consolidação familiar de fluxo de caixa e patrimônio, progresso de metas — tudo
   isso é lógica de servidor. Um front bonito sobre regras erradas é um produto
   errado; o inverso é apenas um produto feio.
2. **Isolamento multi-tenant é decisão de modelagem.** A seção 2.4 exige que
   `tenant_id` exista desde o MVP, mesmo que as Fases 2 e 3 venham depois. Refazer
   isso mais tarde é migração de dados de clientes reais — caro e arriscado.
3. **Compliance mora no backend.** Disclaimers obrigatórios, origem oficial dos
   indicadores (BCB), revisão humana antes de publicar: são regras que precisam ser
   impossíveis de burlar pelo cliente HTTP, e não convenções de UI.
4. **O frontend consome um contrato estável.** Com o OpenAPI publicado
   (`/api/schema/`), as telas são construídas contra tipos gerados, sem
   retrabalho por mudança de payload.

**Exceção deliberada:** o protótipo navegável das telas principais (item do
"Antes da Fase 1" da seção 9) roda **em paralelo**, antes do código de frontend.
Validar a jornada do onboarding self-service com médicos reais é mais barato em
protótipo do que em Angular.

Dentro de cada sprint a ordem é sempre: **modelo → regra de negócio testada →
endpoint → tela**.

---

## 2. Sequência de sprints até o MVP

Sprints de 2 semanas. Escopo = Fase 1 (seção 7.1). A estrutura multi-tenant e o
suporte a cliente com/sem consultor entram desde já; as *funcionalidades* de
consultor ficam para a Fase 2.

| # | Sprint | Entregável | Status |
|---|--------|-----------|--------|
| 0 | Fundação | Repos, Docker Compose, CI, OpenAPI publicado, esqueleto Angular | ✅ feito |
| 1 | Identidade e tenancy | Signup self-service, JWT, tenant plataforma, isolamento testado | ✅ feito |
| 2 | Onboarding | Household, membros (titular/cônjuge/dependentes), renda por membro, patrimônio, dívidas, objetivos | ✅ backend |
| 3 | Fluxo de caixa | Lançamentos mês a mês, orçado x realizado, consolidado e por membro | ✅ backend |
| 4 | Simulador PJ x CLT x Autônomo | Motor tributário versionado, execução por membro, explicações inline | ✅ backend |
| 5 | Metas e dashboard | Metas individuais/compartilhadas, patrimônio líquido, renda combinada | ✅ backend |
| 6 | Módulo educacional | Job mensal, BCB (Selic/IPCA), geração via IA, revisão humana, disclaimers | ✅ backend |
| 7 | Relatório em PDF | Retrato financeiro sob demanda (WeasyPrint) | ✅ backend |
| 8 | Frontend do MVP | Onboarding guiado, fluxo de caixa, simulador, metas, dashboard, educacional | 🔜 em curso |
| 9 | Cobrança | Planos, assinatura, gateway, bloqueio por inadimplência | ⬜ |
| 10 | Hardening e lançamento | LGPD, observabilidade, backup/restore, carga, validação jurídica | ⬜ |

### Detalhamento

**Sprint 0 — Fundação**
Dois repositórios (`finfam-backend`, `finfam-frontend`), Docker Compose com
Postgres e Redis, pipeline de CI rodando lint + testes, schema OpenAPI servido
em `/api/schema/`. *DoD:* `docker compose up` sobe a stack e a suíte passa no CI.

**Sprint 1 — Identidade e tenancy**
`Tenant`, `User` (login por e-mail), signup self-service que cria núcleo familiar
e titular em uma transação. *DoD:* teste que prova que a família A não lê, edita
nem forja dados da família B (`tests/test_isolamento.py`).

**Sprint 2 — Onboarding**
Entidades da seção 5. Regras: um titular por núcleo; dependente não tem fonte de
renda; membro referenciado precisa ser do próprio núcleo. *DoD:* fluxo completo
de onboarding coberto por teste de integração.

**Sprint 3 — Fluxo de caixa**
Lançamento manual com competência (ano/mês), categorias, orçado x realizado.
*DoD:* resumo consolidado bate com a soma por membro + compartilhado.

**Sprint 4 — Simulador**
Motor puro, sem dependência de banco, com tabelas tributárias isoladas em
`rules.py` e versionadas. Cada resultado carrega explicação em linguagem simples
(requisito do self-service) e disclaimer. *DoD:* casos de INSS, IRPF, Fator R e
Anexo III/V cobertos por teste.

**Sprint 5 — Metas e dashboard**
Progresso calculado no servidor (nunca no cliente). Dashboard consolidado da
família com quebra por membro. *DoD:* dashboard de núcleo vazio não quebra.

**Sprint 6 — Módulo educacional**
Celery Beat mensal → BCB (séries 432/433/13522) → Claude com prompt restritivo →
grava como **rascunho**. Publicação exige ação humana no admin. *DoD:* API só
expõe relatório publicado; disclaimer presente em todo payload.

**Sprint 7 — PDF**
Template HTML/CSS renderizado por WeasyPrint, com snapshot dos números no momento
da geração. *DoD:* rota `?formato=html` permite revisar layout sem libs nativas.

**Sprint 8 — Frontend do MVP**
Onboarding guiado com explicação inline em cada etapa, telas de fluxo de caixa,
simulador, metas, dashboard e relatório educacional. *DoD:* jornada
cadastro → onboarding → primeiro dashboard sem tocar no admin.

**Sprint 9 — Cobrança**
Planos, checkout, webhooks do gateway, estados de assinatura e bloqueio.
*DoD:* assinatura inadimplente perde acesso às telas pagas.

**Sprint 10 — Hardening**
Política de privacidade e exclusão de conta (LGPD), logs estruturados, Sentry,
rotina de backup testada com restore, teste de carga do dashboard e **validação
jurídica dos textos do módulo educacional** (bloqueante para o lançamento).

---

## 3. Definition of Done (todo sprint)

- Testes automatizados verdes (`pytest` / `ng test`), sem teste ignorado
- Migrations aplicáveis do zero **e** sobre a base anterior
- Endpoints documentados no OpenAPI, com exemplo de payload
- Nenhum endpoint novo sem teste de isolamento entre núcleos familiares
- Nenhuma string financeira/tributária fora de `rules.py` ou de um model
- Disclaimer presente onde houver número simulado ou conteúdo educacional

---

## 4. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Enquadramento regulatório (CVM) do módulo educacional | Prompt restritivo + revisão humana obrigatória + validação jurídica antes do lançamento (seção 3.6) |
| Tabelas tributárias defasadas | `rules.py` versionado (`VERSAO_REGRAS`), simulação salva registra a versão, testes falham ao mudar valor |
| API do BCB indisponível no dia do job | Retry do Celery; relatório não é gerado sem dado oficial — nunca estimado |
| Vazamento entre núcleos familiares | `tenant_id` em toda entidade + mixin de escopo + suíte de isolamento |
| Onboarding longo demais no self-service | Etapas curtas, salvamento parcial, explicação inline; medir abandono por etapa |
| Custo/latência da IA | Geração mensal em job, nunca no request do usuário |

---

## 5. Depois do MVP

- **Fase 2 (seção 7.2):** perfil de consultor, painel de carteira, anotações de
  sessão, agenda de revisões, PDF com anotações, upsell e migração
  self-service → consultoria preservando histórico.
- **Fase 3 (seção 7.3):** cadastro de consultores como tenants independentes,
  white-label leve (logo/cor), licença por número de clientes ativos, painel de uso.

Os pontos de extensão já estão no código: `Household.consultor`,
`Tenant.tipo`/`marca_*`, `ClientReport.tipo` e `Plan.codigo`.
