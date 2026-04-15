import logging
import time
from typing import Any, Callable

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .models import TaskRunHistory

logger = logging.getLogger("celery.scheduler")


def _normalize_updated_count(result: Any) -> int:
    if result is None:
        return 0
    if isinstance(result, tuple):
        return int(sum(v for v in result if isinstance(v, (int, float))))
    if isinstance(result, (int, float)):
        return int(result)
    return 0


def execute_locked_task(
    *,
    task_name: str,
    lock_ttl: int,
    runner: Callable[[], Any],
) -> dict[str, Any]:
    lock_key = f"task-lock:{task_name}"
    start = time.monotonic()
    started_at = timezone.now()

    if not cache.add(lock_key, str(started_at.timestamp()), timeout=lock_ttl):
        finished_at = timezone.now()
        duration_ms = int((time.monotonic() - start) * 1000)
        payload = {
            "task": task_name,
            "status": "skipped",
            "duration_ms": duration_ms,
            "updated_count": 0,
            "reason": "lock_exists",
        }
        TaskRunHistory.objects.create(
            task_name=task_name,
            status="skipped",
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            updated_count=0,
            details={"reason": "lock_exists"},
        )
        logger.info("task_execution %s", payload)
        return payload

    try:
        with transaction.atomic():
            result = runner()
        updated_count = _normalize_updated_count(result)
        finished_at = timezone.now()
        duration_ms = int((time.monotonic() - start) * 1000)
        payload = {
            "task": task_name,
            "status": "success",
            "duration_ms": duration_ms,
            "updated_count": updated_count,
        }
        TaskRunHistory.objects.create(
            task_name=task_name,
            status="success",
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            updated_count=updated_count,
            details={"result": str(result)},
        )
        logger.info("task_execution %s", payload)
        return payload
    except Exception as exc:
        finished_at = timezone.now()
        duration_ms = int((time.monotonic() - start) * 1000)
        payload = {
            "task": task_name,
            "status": "error",
            "duration_ms": duration_ms,
            "updated_count": 0,
            "error": str(exc),
        }
        TaskRunHistory.objects.create(
            task_name=task_name,
            status="error",
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            updated_count=0,
            error=str(exc),
        )
        logger.exception("task_execution %s", payload)
        raise
    finally:
        cache.delete(lock_key)
