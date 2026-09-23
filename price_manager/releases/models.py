from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from core.task_runner import dispatch_after_commit
from releases.rendering import clean_html, html_to_markdown


class Release(models.Model):
    """A released version of the app and its write-up for managers.

    `summary` is what every user gets in «Оповещения» when the release is
    published; the article is the full text behind the notification's link —
    what changed in the managers' daily work and what to watch out for. The
    article is written and shown as HTML; `article_markdown` duplicates it.

    Publishing (is_published=True) sends the summary exactly once:
    `notified_at` records that it went out, so later edits to a published
    release never re-notify.
    """

    version = models.CharField(
        max_length=32,
        unique=True,
        # The version is the article's URL, so keep it path-safe.
        validators=[RegexValidator(
            r'^[0-9A-Za-z][0-9A-Za-z._-]*$',
            'Только латиница, цифры, точка, дефис и подчёркивание — например, 1.4.0.',
        )],
        verbose_name='Версия',
    )
    title = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='Заголовок',
        help_text='Необязательно. Например: «Приоритеты поставщиков».',
    )
    summary = models.TextField(
        verbose_name='Кратко',
        help_text='Пара предложений. Приходит всем пользователям в «Оповещения».',
    )
    article_html = models.TextField(
        verbose_name='Статья (HTML)',
        help_text=(
            'Что изменилось с точки зрения менеджера: как это влияет на работу '
            'и на что обратить внимание. Скрипты, стили и обработчики событий '
            'вырезаются при сохранении.'
        ),
    )
    # A copy, never edited by hand: rebuilt from article_html on every save,
    # so the two can not drift apart.
    article_markdown = models.TextField(
        blank=True,
        editable=False,
        verbose_name='Статья (Markdown)',
    )
    released_at = models.DateField(default=timezone.localdate, verbose_name='Дата выхода')
    is_published = models.BooleanField(
        default=False,
        verbose_name='Опубликовано',
        help_text='При публикации краткое описание рассылается всем пользователям — один раз.',
    )
    notified_at = models.DateTimeField(null=True, blank=True, verbose_name='Оповещение отправлено')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='releases',
        verbose_name='Автор',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Создано')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Изменено')

    class Meta:
        verbose_name = 'Версия'
        verbose_name_plural = 'Версии'
        ordering = ('-released_at', '-pk')

    def __str__(self):
        return f'{self.version} — {self.title}' if self.title else self.version

    def get_absolute_url(self):
        return reverse('release-detail', kwargs={'version': self.version})

    def save(self, *args, **kwargs):
        # Stored clean, so the detail page can render it with |safe.
        self.article_html = clean_html(self.article_html)
        self.article_markdown = html_to_markdown(self.article_html)
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'article_html' in update_fields:
            kwargs['update_fields'] = {*update_fields, 'article_markdown'}
        super().save(*args, **kwargs)
        # Every save path (admin form, admin action, shell) announces a
        # published release; the task itself makes a repeat dispatch a no-op.
        if self.is_published and self.notified_at is None:
            from releases.tasks import notify_release_task

            dispatch_after_commit(notify_release_task, self.pk)
