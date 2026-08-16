import uuid

from django.db import models


class TimeStampedModel(models.Model):
    """Base com id UUID e carimbos de tempo — usada por todo o domínio."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantScopedQuerySet(models.QuerySet):
    def do_tenant(self, tenant):
        return self.filter(tenant=tenant)


class TenantScopedModel(TimeStampedModel):
    """Entidade pertencente a um tenant (workspace de consultor ou plataforma).

    O `tenant_id` é redundante em entidades que já descendem de Household, mas é
    mantido explicitamente para que qualquer consulta possa ser filtrada por
    tenant sem JOIN — é a garantia de isolamento descrita na seção 2.4 da
    especificação.
    """

    tenant = models.ForeignKey(
        "tenancy.Tenant",
        on_delete=models.CASCADE,
        related_name="%(class)s_set",
    )

    objects = TenantScopedQuerySet.as_manager()

    class Meta:
        abstract = True
