from celery import shared_task
from django.conf import settings
from django.utils import timezone

from core.task_runner import execute_locked_task
from developers import bitrix24

TITLE_PREFIX = 'Обратная связь PM'
TITLE_SNIPPET_LENGTH = 80


def build_title(feedback) -> str:
    first_line = feedback.message.strip().splitlines()[0] if feedback.message.strip() else ''
    if len(first_line) > TITLE_SNIPPET_LENGTH:
        first_line = first_line[:TITLE_SNIPPET_LENGTH - 1].rstrip() + '…'
    return f'{TITLE_PREFIX} #{feedback.pk}: {first_line}'


def build_description(feedback) -> str:
    author = feedback.author
    if author is None:
        who = 'не указан'
    else:
        full_name = author.get_full_name()
        who = f'{full_name} ({author.get_username()})' if full_name else author.get_username()
        if author.email:
            who += f', {author.email}'
    created = timezone.localtime(feedback.created_at).strftime('%d.%m.%Y %H:%M')
    lines = [
        f'Автор: {who}',
        f'Страница: {feedback.page_url or "не указана"}',
        f'Отправлено: {created}',
        '',
        feedback.message,
    ]
    return '\n'.join(lines)


def send_feedback(feedback_id: int) -> int:
    """Create the Bitrix24 task for one Feedback. Returns 1 if a task was created."""
    from developers.models import Feedback

    feedback = Feedback.objects.select_related('author').filter(pk=feedback_id).first()
    # Already sent: a re-send from the admin or a duplicate delivery must not
    # open a second task for the same message.
    if feedback is None or feedback.status == Feedback.Status.SENT:
        return 0

    if not bitrix24.is_configured():
        feedback.status = Feedback.Status.FAILED
        feedback.error = 'Интеграция с Bitrix24 не настроена (BITRIX24_FEEDBACK_WEBHOOK, BITRIX24_FEEDBACK_RESPONSIBLE_ID).'
        feedback.save(update_fields=['status', 'error'])
        return 0

    try:
        task_id = bitrix24.create_task(
            title=build_title(feedback),
            description=build_description(feedback),
            responsible_id=settings.BITRIX24_FEEDBACK_RESPONSIBLE_ID,
        )
    except bitrix24.Bitrix24Error as exc:
        feedback.status = Feedback.Status.FAILED
        feedback.error = str(exc)
        feedback.save(update_fields=['status', 'error'])
        raise

    feedback.status = Feedback.Status.SENT
    feedback.bitrix_task_id = task_id
    feedback.sent_at = timezone.now()
    feedback.error = ''
    feedback.save(update_fields=['status', 'bitrix_task_id', 'sent_at', 'error'])
    return 1


@shared_task(
    name='developers.send_feedback',
    autoretry_for=(bitrix24.Bitrix24Unavailable,),
    retry_backoff=60,
    max_retries=3,
)
def send_feedback_task(feedback_id: int) -> dict:
    # Lock per message, not per task name: a shared lock would make a second
    # message sent while the first is in flight skip silently.
    # atomic=False: the runner waits on Bitrix24 between its reads and writes.
    return execute_locked_task(
        task_name=f'developers.send_feedback:{feedback_id}',
        lock_ttl=60 * 5,
        runner=lambda: send_feedback(feedback_id),
        atomic=False,
    )
