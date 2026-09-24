from celery import shared_task
from django.utils import timezone
from django.utils.html import escape

from core.task_runner import execute_locked_task

LINK_TEXT = 'Читать статью'


def build_message(release) -> str:
    """Notification text. The panel renders `message` with |safe, so escape."""
    heading = f'Вышла версия {escape(release.version)}'
    if release.title:
        heading += f': {escape(release.title)}'
    return f'<strong>{heading}</strong><br>{escape(release.summary.strip())}'


def notify_release(release_id: int) -> int:
    """Put the release summary into every active user's notifications, once.

    Returns the number of notifications created. A draft, a deleted release or
    one already announced creates none, so a duplicate dispatch is harmless.
    """
    from django.contrib.auth import get_user_model

    from core.models import LevelChoices, NotificationKind, PersistentNotification
    from releases.models import Release

    release = Release.objects.select_for_update().filter(pk=release_id).first()
    if release is None or not release.is_published or release.notified_at is not None:
        return 0

    message = build_message(release)
    link = release.get_absolute_url()
    user_ids = get_user_model().objects.filter(is_active=True).values_list('pk', flat=True)
    created = PersistentNotification.objects.bulk_create(
        [
            PersistentNotification(
                user_id=user_id,
                level=LevelChoices.INFO,
                message=message,
                link=link,
                link_text=LINK_TEXT,
                kind=NotificationKind.RELEASE,
            )
            for user_id in user_ids
        ],
        batch_size=500,
    )
    # .update(), not .save(): save() is what dispatches this task.
    Release.objects.filter(pk=release.pk).update(notified_at=timezone.now())
    return len(created)


@shared_task(name='releases.notify_release')
def notify_release_task(release_id: int) -> dict:
    return execute_locked_task(
        task_name=f'releases.notify_release:{release_id}',
        lock_ttl=300,
        runner=lambda: notify_release(release_id),
    )
