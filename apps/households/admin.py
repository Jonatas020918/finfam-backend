from django.contrib import admin

from .models import Asset, Debt, Household, IncomeSource, LifeGoal, Member


class MemberInline(admin.TabularInline):
    model = Member
    extra = 0
    fields = ("tipo", "nome", "data_nascimento", "profissao", "usuario")


@admin.register(Household)
class HouseholdAdmin(admin.ModelAdmin):
    list_display = ("nome", "modo", "tenant", "consultor", "onboarding_concluido_em")
    list_filter = ("modo", "tenant")
    search_fields = ("nome",)
    inlines = [MemberInline]


for modelo in (Member, IncomeSource, Asset, Debt, LifeGoal):
    admin.site.register(modelo)
