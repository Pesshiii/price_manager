from django.conf import settings
from django.db import models


class Feedback(models.Model):
    """A message to the developers. Each one becomes its own Bitrix24 task.

    The row is the record of what was sent: it is kept whether or not the task
    got created, so a message is never lost to a Bitrix24 outage and can be
    re-sent from the admin.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Ожидает отправки'
        SENT = 'sent', 'Задача создана'
        FAILED = 'failed', 'Ошибка отправки'

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='developer_feedback',
        verbose_name='Автор',
    )
    message = models.TextField(verbose_name='Сообщение')
    page_url = models.CharField(max_length=500, blank=True, verbose_name='Страница')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Отправлено')
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name='Статус',
    )
    bitrix_task_id = models.PositiveBigIntegerField(
        null=True, blank=True, verbose_name='Задача в Bitrix24'
    )
    sent_at = models.DateTimeField(null=True, blank=True, verbose_name='Задача создана')
    error = models.TextField(blank=True, verbose_name='Ошибка')

    class Meta:
        verbose_name = 'Обращение к разработчикам'
        verbose_name_plural = 'Обращения к разработчикам'
        ordering = ('-created_at',)

    def __str__(self):
        return f'Обращение #{self.pk}'
