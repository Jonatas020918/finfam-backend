# FinFam — Backend

API da Plataforma de Consultoria Financeira e Familiar para médicos e
profissionais de saúde. Django + Django REST Framework + PostgreSQL.

Escopo atual: **Fase 1 — MVP Self-Service** (seção 7.1 da especificação).
O plano completo está em [ROADMAP.md](ROADMAP.md).

## Stack

| Camada | Tecnologia |
|---|---|
| API / regras de negócio | Django 6 + DRF, JWT (SimpleJWT) |
| Banco | PostgreSQL 17 |
| Tarefas agendadas | Celery + Redis (relatório educacional mensal) |
| PDF | WeasyPrint (HTML/CSS → PDF, no backend) |
| IA | SDK Python da Anthropic |
| Documentação da API | drf-spectacular (OpenAPI 3) |

## Subindo com Docker

```bash
cp .env.example .env && docker compose up --build
```

- API: http://localhost:8000/api/
- Documentação interativa: http://localhost:8000/api/docs/
- Admin (revisão do módulo educacional): http://localhost:8000/admin/

```bash
docker compose exec api python manage.py createsuperuser
```

## Ambiente local sem Docker

```bash
python -m venv .venv && .venv/Scripts/activate
pip install -r requirements/dev.txt
python manage.py migrate
python manage.py runserver
```

Sem `DATABASE_URL`, o projeto cai em SQLite — suficiente para rodar a suíte de
testes, mas o ambiente de referência é PostgreSQL.

## Testes

```bash
pytest
```

```bash
pytest --cov=apps --cov-report=term-missing
```

## Organização

```
apps/
  common/      base multi-tenant (TenantScopedModel, mixin de escopo da API)
  tenancy/     Tenant — workspace da plataforma e, nas Fases 2/3, do consultor
  accounts/    User (login por e-mail), signup self-service, JWT
  households/  núcleo familiar, membros, renda, patrimônio, dívidas, objetivos
  cashflow/    lançamentos manuais e consolidação mensal
  simulators/  motor tributário PJ x CLT x Autônomo (rules.py + services.py)
  goals/       metas individuais e compartilhadas
  education/   relatório mensal: BCB → IA → revisão humana → publicação
  reports/     dashboard consolidado e retrato financeiro em PDF
  billing/     planos e assinaturas
```

## Pontos de atenção

**Tabelas tributárias.** Todos os valores de INSS, IRPF e Simples Nacional estão
em `apps/simulators/rules.py`, versionados por `VERSAO_REGRAS`. Eles refletem a
legislação de **2025** e precisam ser conferidos a cada virada de ano — os testes
falham de propósito quando um valor muda, forçando a revisão consciente.

**Módulo educacional.** O job mensal grava o relatório como `rascunho`; a API só
expõe relatórios `publicado`. A publicação é uma ação humana no admin. Esse
fluxo é controle de compliance (seção 3.6), não conveniência operacional.

**Isolamento.** Toda entidade do domínio carrega `tenant_id` e todo endpoint de
cliente passa por `HouseholdScopedMixin`. `tests/test_isolamento.py` é a rede de
segurança — nenhum endpoint novo deve entrar sem um teste equivalente.
