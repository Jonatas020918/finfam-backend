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
}
