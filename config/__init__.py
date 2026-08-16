def _load_celery():
    """Carrega o app Celery apenas quando a dependência está instalada.

    Permite rodar a suíte de testes e comandos do Django sem Celery/Redis local.
    """
    try:
        from .celery import app as celery_app
    except ImportError:  # pragma: no cover - ambiente sem celery
        return None
    return celery_app


celery_app = _load_celery()

__all__ = ("celery_app",)
