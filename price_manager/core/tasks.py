from celery import shared_task
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from core.utils import update_cart_items
from core.task_runner import execute_locked_task

def _notify_import(user_id: int | None, shopping_tab_id: int, level: str, message: str) -> None:
    from django.contrib.auth import get_user_model
    from core.models import PersistentNotification

    if not user_id or not get_user_model().objects.filter(pk=user_id).exists():
        return
    PersistentNotification.objects.create(user_id=user_id, level=level, message=message)


@shared_task(name="core.update_cart_items")
def update_cart_items_task(
    shopping_tab_id: int,
    query_column: str,
    quantity_column: str | None = None,
    user_id: int | None = None,
) -> dict:
    """Массовое создание позиций заявки из прикреплённого файла."""
    from core.models import ShoppingTab

    tab_name = (
        ShoppingTab.objects.filter(pk=shopping_tab_id).values_list('name', flat=True).first()
        or shopping_tab_id
    )

    try:
        payload = execute_locked_task(
            task_name=f"core.update_cart_items:{shopping_tab_id}",
            lock_ttl=60 * 30,
            runner=lambda: update_cart_items(shopping_tab_id, query_column, quantity_column),
        )
    except Exception as exc:
        _notify_import(
            user_id, shopping_tab_id, 'danger',
            f'Импорт заявки «{tab_name}» завершился с ошибкой: {exc}',
        )
        raise

    status = payload.get('status')
    if status == 'skipped':
        _notify_import(
            user_id, shopping_tab_id, 'warning',
            f'Импорт заявки «{tab_name}» пропущен: он уже выполняется.',
        )
    else:
        _notify_import(
            user_id, shopping_tab_id, 'success',
            f'Импорт заявки «{tab_name}» завершён. Создано позиций: {payload.get("updated_count", 0)}.',
        )
    return payload


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