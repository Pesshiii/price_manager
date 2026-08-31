from celery import shared_task
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from datetime import timedelta
from core.utils import update_cart_items, build_shopping_tab_export
from core.task_runner import execute_locked_task


def _notify(
    user_id: int | None,
    level: str,
    message: str,
    link: str | None = None,
    link_text: str | None = None,
) -> None:
    """Постоянное уведомление пользователю, при необходимости с кнопкой-ссылкой."""
    from django.contrib.auth import get_user_model
    from core.models import PersistentNotification

    if not user_id or not get_user_model().objects.filter(pk=user_id).exists():
        return
    PersistentNotification.objects.create(
        user_id=user_id,
        level=level,
        message=message,
        link=link,
        link_text=link_text,
    )


def _tab_name(shopping_tab_id: int) -> str:
    """Название заявки, экранированное: панель уведомлений рендерит message через |safe."""
    from core.models import ShoppingTab

    name = ShoppingTab.objects.filter(pk=shopping_tab_id).values_list('name', flat=True).first()
    return escape(name) if name else str(shopping_tab_id)


@shared_task(name="core.update_cart_items")
def update_cart_items_task(
    shopping_tab_id: int,
    query_column: str,
    quantity_column: str | None = None,
    user_id: int | None = None,
) -> dict:
    """Массовое создание позиций заявки из прикреплённого файла."""
    tab_name = _tab_name(shopping_tab_id)

    try:
        payload = execute_locked_task(
            task_name=f"core.update_cart_items:{shopping_tab_id}",
            lock_ttl=60 * 30,
            runner=lambda: update_cart_items(shopping_tab_id, query_column, quantity_column),
        )
    except Exception as exc:
        _notify(user_id, 'danger', f'Импорт заявки «{tab_name}» завершился с ошибкой: {escape(exc)}')
        raise

    if payload.get('status') == 'skipped':
        _notify(user_id, 'warning', f'Импорт заявки «{tab_name}» пропущен: он уже выполняется.')
    else:
        _notify(
            user_id,
            'success',
            f'Импорт заявки «{tab_name}» завершён. Создано позиций: {payload.get("updated_count", 0)}.',
            link=reverse('shopping-tab-detail', kwargs={'pk': shopping_tab_id}),
            link_text='Открыть заявку',
        )
    return payload


@shared_task(name="core.export_shopping_tab")
def export_shopping_tab_task(shopping_tab_id: int, user_id: int | None = None) -> dict:
    """Выгрузка позиций заявки в xlsx. Ссылка на скачивание приходит в уведомлении."""
    tab_name = _tab_name(shopping_tab_id)
    created = {}

    def _runner():
        export = build_shopping_tab_export(shopping_tab_id, user_id)
        created['export'] = export
        return export.rows_count

    try:
        payload = execute_locked_task(
            task_name=f"core.export_shopping_tab:{shopping_tab_id}",
            lock_ttl=60 * 15,
            runner=_runner,
        )
    except Exception as exc:
        _notify(user_id, 'danger', f'Экспорт заявки «{tab_name}» завершился с ошибкой: {escape(exc)}')
        raise

    export = created.get('export')
    if payload.get('status') == 'skipped':
        _notify(user_id, 'warning', f'Экспорт заявки «{tab_name}» пропущен: он уже выполняется.')
    elif export is not None:
        _notify(
            user_id,
            'success',
            f'Экспорт заявки «{tab_name}» готов. Строк: {export.rows_count}.',
            link=reverse('shopping-tab-export-download', kwargs={'pk': export.pk}),
            link_text='Скачать файл',
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
