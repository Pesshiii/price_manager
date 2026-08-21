from celery import shared_task
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from core.utils import update_cart_items
from core.task_runner import execute_locked_task

@shared_task(name="core.update_cart_items")
def update_cart_items_task(shopping_tab_id: int) -> dict:

    start_time = timezone.now()
    updated_count = update_cart_items(shopping_tab_id)
    duration_ms = (timezone.now() - start_time).total_seconds() * 1000

    return {
        "status": "success",
        "updated_count": updated_count,
        "duration_ms": duration_ms,
    }


@shared_task(name="core.cleanup_persistent_notifications")
def cleanup_persistent_notifications_task() -> dict:
    from core.models import PersistentNotification

    def runner():
        cutoff = timezone.now() - timedelta(hours=settings.PERSISTENT_NOTIFICATION_TTL_HOURS)
        deleted_count, _ = PersistentNotification.objects.filter(created_at__lt=cutoff).delete()
        return deleted_count

    return execute_locked_task(
        task_name="core.cleanup_persistent_notifications",
        lock_ttl=300,
        runner=runner,
    )