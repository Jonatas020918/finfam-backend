from django.contrib import admin
from django.utils import timezone

from .models import EducationalReport, IndicadorMensal, StatusRelatorio


@admin.register(IndicadorMensal)
class IndicadorMensalAdmin(admin.ModelAdmin):
    """Somente leitura: quem escreve aqui é o job diário, a partir do BCB."""

    list_display = (
        "__str__",
        "selic_meta_percentual",
        "ipca_mes_percentual",
        "ipca_12m_percentual",
        "completo",
        "sincronizado_em",
    )
    list_filter = ("ano",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(EducationalReport)
class EducationalReportAdmin(admin.ModelAdmin):
    """Onde a revisão humana obrigatória acontece antes da publicação."""

    list_display = ("titulo", "mes", "ano", "status", "selic_meta_percentual", "ipca_mes_percentual")
    list_filter = ("status", "ano")
    readonly_fields = ("selic_meta_percentual", "selic_variacao_mes",
                       "ipca_mes_percentual", "ipca_12m_percentual", "modelo_ia")
    actions = ["publicar"]

    @admin.action(description="Publicar relatórios revisados")
    def publicar(self, request, queryset):
        atualizados = queryset.update(
            status=StatusRelatorio.PUBLICADO,
            publicado_em=timezone.now(),
            revisado_por=request.user,
        )
        self.message_user(request, f"{atualizados} relatório(s) publicado(s).")
