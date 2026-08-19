import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Papel, User
from apps.billing.gateways import criar_assinatura_em_teste
from apps.households.models import Household, ModoUso, TipoMembro
from apps.tenancy.models import Tenant, TenantTipo


@pytest.fixture(autouse=True)
def ambiente_de_teste(settings):
    """A suíte fala HTTP puro e não roda collectstatic.

    Sem isso, o redirect para HTTPS e o manifest do WhiteNoise (ambos corretos
    em produção) fariam todo request de teste falhar por motivos de infra.
    """
    settings.SECURE_SSL_REDIRECT = False
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def tenant_plataforma(db):
    tenant, _ = Tenant.objects.get_or_create(
        tipo=TenantTipo.PLATAFORMA,
        defaults={"nome": "Plataforma (self-service)", "slug": "plataforma"},
    )
    return tenant


@pytest.fixture
def familia(db, tenant_plataforma):
    """Fábrica de núcleo familiar completo com titular logável.

    Devolve (household, titular_membro, user) para que os testes de isolamento
    possam montar duas famílias independentes com poucas linhas.
    """

    def _criar(email="medico@exemplo.com", nome="Ana Souza", nome_familia="Família Souza"):
        user = User.objects.create_user(
            email=email, password="senha-muito-segura-123", nome_completo=nome,
            papel=Papel.CLIENTE, tenant=tenant_plataforma,
        )
        household = Household.objects.create(
            tenant=tenant_plataforma, nome=nome_familia, modo=ModoUso.SELF_SERVICE
        )
        titular = household.membros.create(
            tenant=tenant_plataforma, tipo=TipoMembro.TITULAR, nome=nome, usuario=user
        )
        # Espelha o cadastro real: toda conta nasce com período de teste. Sem
        # isso o fixture criaria um estado que a aplicação nunca produz.
        criar_assinatura_em_teste(household)
        return household, titular, user

    return _criar


@pytest.fixture
def familia_autenticada(api, familia):
    household, titular, user = familia()
    api.force_authenticate(user=user)
    return household, titular, user
