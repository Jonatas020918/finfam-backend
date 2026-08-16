from django.contrib import admin
from django.utils import timezone

from .models import EducationalReport, StatusRelatorio


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
