from django.apps import AppConfig


class CommonConfig(AppConfig):
    name = "apps.common"

    def ready(self):
        from . import checks  # noqa: F401  (registra as verificações de deploy)
