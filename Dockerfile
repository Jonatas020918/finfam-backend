# syntax=docker/dockerfile:1

FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Só o necessário para compilar o psycopg e checar a saúde do container. O PDF
# é gerado em Python puro, então Pango, Cairo e GDK-Pixbuf saíram da imagem.
RUN apt-get update && apt-get install --no-install-recommends -y \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements/ requirements/
RUN pip install --upgrade pip && pip install -r requirements/base.txt

COPY . .

# Coleta os estáticos na imagem, não no runtime.
#
# Não é cosmético: o STORAGES usa CompressedManifestStaticFilesStorage, que é
# estrito. Sem o manifesto, com DEBUG=False, qualquer template que use
# {% static %} levanta ValueError — e o /admin/ inteiro responde 500. O admin é
# onde se cadastram os Price do Stripe e se administram os planos.
#
# As variáveis abaixo existem só para o settings carregar durante o build; nada
# aqui vai para o runtime, que lê o .env de verdade.
RUN DEBUG=False \
    SECRET_KEY=apenas-para-o-build-coletar-estaticos-nao-e-segredo-real \
    DATABASE_URL=sqlite:////tmp/build.sqlite3 \
    python manage.py collectstatic --noinput --clear

# Usuário sem privilégios — o container nunca precisa de root em runtime.
RUN adduser --disabled-password --gecos "" appuser \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# /api/schema/ exige autenticação e devolveria 401: o container ficaria eternamente
# unhealthy e o orquestrador o reiniciaria em laço.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/saude/ > /dev/null || exit 1

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]


# --- Imagem de desenvolvimento (inclui pytest, ruff e o runserver) ---------
FROM base AS dev

USER root
RUN pip install -r requirements/dev.txt
USER appuser

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
