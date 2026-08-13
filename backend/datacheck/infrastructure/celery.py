from celery import Celery

from datacheck.core.settings import WorkerSettings


def create_celery_app(settings: WorkerSettings | None = None) -> Celery:
    """Build the worker application without registering product or smoke tasks."""
    resolved_settings = settings or WorkerSettings.from_environment()
    celery = Celery(
        "datacheck",
        broker=resolved_settings.celery_broker_url.get_secret_value(),
    )
    celery.conf.update(
        accept_content=["json"],
        task_serializer="json",
        result_serializer="json",
        broker_connection_retry_on_startup=True,
    )
    return celery


# Celery's CLI imports this object and therefore resolves worker configuration here.
# Constructing the object does not establish a Redis connection or publish a task.
celery_app = create_celery_app()
