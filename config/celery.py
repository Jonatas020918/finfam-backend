import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("finfam")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    # Dia 2 de cada mês, 06:00 — dá folga para o BCB publicar os índices do mês anterior.
    "gerar-relatorio-educacional-mensal": {
        "task": "apps.education.tasks.gerar_relatorio_mensal",
        "schedule": crontab(minute=0, hour=6, day_of_month=2),
    },
    # Todo dia às 07:30. A meta Selic muda a cada Copom e o IPCA do mês sai por
    # volta do dia 10 do mês seguinte — esperar o job mensal deixaria a tela do
    # cliente com número velho por semanas. São três GETs por dia.
    "atualizar-indicadores-bcb": {
        "task": "apps.education.tasks.atualizar_indicadores",
        "schedule": crontab(minute=30, hour=7),
    },
}
