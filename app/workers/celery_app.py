"""app/workers/celery_app.py — Celery application instance and configuration.

The single `celery_app` object is imported by:
  - app/workers/tasks.py       (task definitions)
  - CLI startup commands       (celery -A app.workers.celery_app worker ...)
"""
from celery import Celery

from app.config import settings

celery_app = Celery(
    "route_optimizer",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Time limits — soft limit logs a warning; hard limit terminates the task
    task_soft_time_limit=15,   # seconds
    task_time_limit=30,        # seconds
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Prevent tasks from running on the same worker that enqueued them
    task_always_eager=False,
)
