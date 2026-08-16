"""Cria o tenant "plataforma", que abriga todos os clientes self-service."""

from django.db import migrations


def criar_tenant_plataforma(apps, schema_editor):
    Tenant = apps.get_model("tenancy", "Tenant")
    Tenant.objects.get_or_create(
        tipo="plataforma",
        defaults={"nome": "Plataforma (self-service)", "slug": "plataforma"},
    )


def remover_tenant_plataforma(apps, schema_editor):
    Tenant = apps.get_model("tenancy", "Tenant")
    Tenant.objects.filter(tipo="plataforma", slug="plataforma").delete()


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0001_initial")]

    operations = [
        migrations.RunPython(criar_tenant_plataforma, remover_tenant_plataforma),
    ]
