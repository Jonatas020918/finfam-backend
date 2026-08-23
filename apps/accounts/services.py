"""Provisionamento de conta nova.

Um único lugar para a sequência "usuário + núcleo familiar + membro titular +
assinatura em teste" — usada pelo cadastro por senha e pelo login com Google.
As duas entradas não podem divergir no que uma conta nova ganha: se um dia
alguém adicionar um passo aqui (um e-mail de boas-vindas, por exemplo), as
duas formas de entrar precisam do mesmo passo, sem lembrar de repetir em dois
lugares.
"""

from django.db import transaction

from apps.billing.gateways import criar_assinatura_em_teste
from apps.households.models import Household, ModoUso, TipoMembro
from apps.tenancy.models import Tenant, TenantTipo

from .models import Papel, User


@transaction.atomic
def provisionar_conta(
    *,
    email: str,
    nome_completo: str,
    password: str | None,
    telefone: str = "",
    nome_familia: str = "",
    google_sub: str | None = None,
    aceite_termos_versao: str = "",
    aceite_termos_em=None,
    aceite_termos_ip: str | None = None,
) -> User:
    """Cria a conta e tudo que ela precisa para começar a usar a plataforma.

    O aceite dos termos é passado pronto (ou vazio) por quem chama — aqui não
    se decide se houve consentimento, só se grava o que já foi obtido. Uma
    conta criada sem aceite nasce com `termos_aceitos=False`, e a tela é quem
    decide o que fazer com isso (pedir o aceite antes de liberar o resto).
    """
    tenant, _ = Tenant.objects.get_or_create(
        tipo=TenantTipo.PLATAFORMA,
        defaults={"nome": "Plataforma (self-service)", "slug": "plataforma"},
    )
    user = User.objects.create_user(
        email=email,
        password=password,
        nome_completo=nome_completo,
        telefone=telefone,
        papel=Papel.CLIENTE,
        tenant=tenant,
        google_sub=google_sub,
        aceite_termos_versao=aceite_termos_versao,
        aceite_termos_em=aceite_termos_em,
        aceite_termos_ip=aceite_termos_ip,
    )

    nome_da_familia = nome_familia or f"Família {nome_completo.split()[-1]}"
    household = Household.objects.create(
        tenant=tenant, nome=nome_da_familia, modo=ModoUso.SELF_SERVICE
    )
    household.membros.create(
        tenant=tenant,
        tipo=TipoMembro.TITULAR,
        nome=nome_completo,
        usuario=user,
    )
    # Toda conta nova nasce com período de teste: o bloqueio só faz sentido
    # depois que a pessoa conheceu o produto.
    criar_assinatura_em_teste(household)
    return user
