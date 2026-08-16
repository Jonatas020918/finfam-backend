from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("email",)
    list_display = ("email", "nome_completo", "papel", "tenant", "is_active")
    list_filter = ("papel", "is_active", "tenant")
    search_fields = ("email", "nome_completo")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Perfil", {"fields": ("nome_completo", "telefone", "papel", "tenant")}),
        ("Permissões", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Compliance", {"fields": ("aceite_disclaimer_educacional_em",)}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "nome_completo", "papel", "password1", "password2"),
        }),
    )
