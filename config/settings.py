"""
Configuração do backend da Plataforma de Consultoria Financeira e Familiar.

12-factor: tudo que muda entre ambientes vem de variáveis de ambiente
(ver .env.example). O mesmo settings serve dev, docker, CI e produção.
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["*"]),
    CORS_ALLOWED_ORIGINS=(list, ["http://localhost:4200"]),
    DATABASE_URL=(str, "sqlite:///" + str(BASE_DIR / "db.sqlite3")),
    CELERY_BROKER_URL=(str, "redis://localhost:6379/0"),
    ANTHROPIC_API_KEY=(str, ""),
    ANTHROPIC_MODEL=(str, "claude-sonnet-5"),
    BCB_API_BASE_URL=(str, "https://api.bcb.gov.br/dados/serie/bcdata.sgs"),
)

environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="dev-insecure-key-nao-use-em-producao")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # terceiros
    "rest_framework",
    "corsheaders",
    "drf_spectacular",
    # apps do domínio
    "apps.common",
    "apps.tenancy",
    "apps.accounts",
    "apps.households",
    "apps.cashflow",
    "apps.simulators",
    "apps.goals",
    "apps.education",
    "apps.reports",
    "apps.billing",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": env.db_url("DATABASE_URL")}
DATABASES["default"]["ATOMIC_REQUESTS"] = True

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- DRF -------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    # Sem DEFAULT_THROTTLE_CLASSES as taxas abaixo são ignoradas pelo DRF —
    # login e cadastro ficavam sem limite de tentativas.
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "30/min",
        "user": "1000/hour",
        # Redefinição de senha dispara e-mail: limite bem mais estreito, para
        # que ninguém use o formulário como ferramenta de spam.
        "redefinicao_senha": "5/hour",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "UPDATE_LAST_LOGIN": True,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "FinFam API",
    "DESCRIPTION": "API da plataforma de consultoria financeira e familiar para médicos.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")

# Atrás de HTTPS, o Django compara a origem do formulário com esta lista antes
# de aceitar qualquer POST de sessão. Sem ela, o login do admin no domínio de
# produção falha com "CSRF verification failed" e nada explica o motivo.
# O padrão acompanha o CORS: é a mesma lista de origens confiáveis.
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=CORS_ALLOWED_ORIGINS)

# --- Celery ----------------------------------------------------------------

CELERY_BROKER_URL = env("CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=CELERY_BROKER_URL)
CELERY_TASK_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
# O agendamento em si fica em config/celery.py (precisa do objeto crontab).

# --- E-mail transacional ---------------------------------------------------

# Sem SMTP configurado, o e-mail vai para o console: em desenvolvimento o link
# de redefinição aparece no terminal, e nada trava por falta de credencial.
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default=(
        "django.core.mail.backends.smtp.EmailBackend"
        if env("EMAIL_HOST", default="")
        else "django.core.mail.backends.console.EmailBackend"
    ),
)
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")

# A criptografia segue a porta, que é como os provedores documentam o serviço.
# A Hostinger publica as duas: 465 com SSL direto e 587 com STARTTLS. Ligar as
# duas ao mesmo tempo é erro de configuração — o Django recusa a conexão — e
# deixar as duas desligadas manda a senha do mailbox em texto puro.
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=EMAIL_PORT == 465)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=not EMAIL_USE_SSL)

# Sem timeout, um SMTP que não responde segura o worker até o gunicorn matá-lo.
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=10)

DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Pulso <nao-responda@pulso.app>")

# Onde o cliente clica: o link do e-mail leva a uma tela, não à API.
FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:4200")

# Validade do link de redefinição (segundos). 24h dá folga para quem só abre o
# e-mail à noite, sem deixar um link vivo por tempo demais.
PASSWORD_RESET_TIMEOUT = env.int("PASSWORD_RESET_TIMEOUT", default=60 * 60 * 24)


# --- Assinatura -------------------------------------------------------------

# Dias de teste concedidos no cadastro. Sem teste, o cliente bate num bloqueio
# antes de ver o produto — e ninguém compra o que não experimentou.
ASSINATURA_TRIAL_DIAS = env.int("ASSINATURA_TRIAL_DIAS", default=14)

# Dias de acesso mantidos depois de uma cobrança falhar. Cartão vencido é o
# motivo mais comum, e cortar no mesmo dia perde cliente que só precisava
# atualizar o número.
ASSINATURA_CARENCIA_DIAS = env.int("ASSINATURA_CARENCIA_DIAS", default=5)

# Caminho da classe do gateway.
#
# Enquanto a conta do Stripe não estiver configurada, o padrão é o mock, que
# simula as chamadas de rede e exercita todo o resto do fluxo. Para usar o
# Stripe de verdade, troque por "apps.billing.gateways_stripe.GatewayStripe" e
# preencha as chaves abaixo — é a única mudança necessária.
ASSINATURA_GATEWAY = env(
    "ASSINATURA_GATEWAY", default="apps.billing.gateways_stripe.GatewayStripeMock"
)

STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_PUBLIC_KEY = env("STRIPE_PUBLIC_KEY", default="")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default="")


# --- Funcionalidades por fase ----------------------------------------------

# O modo consultoria (Fase 2 — seção 7.2) tem a estrutura de dados pronta desde
# o MVP, mas nenhuma funcionalidade de consultor construída: não existe painel,
# anotação de sessão nem cobrança do plano. Enquanto esta flag for falsa, a
# interface anuncia o modo como "em breve" em vez de oferecê-lo — prometer o que
# não existe é o jeito mais rápido de perder a confiança de quem paga.
CONSULTORIA_DISPONIVEL = env.bool("FEATURE_CONSULTORIA", default=False)


# --- Integrações -----------------------------------------------------------

ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = env("ANTHROPIC_MODEL")
BCB_API_BASE_URL = env("BCB_API_BASE_URL")

# --- Segurança em produção -------------------------------------------------

if not DEBUG:
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
