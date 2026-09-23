from django.conf import settings
from django.contrib import admin, messages
from django.db.models import Q
from django.utils.html import format_html
from django.utils.text import Truncator

from core.task_runner import dispatch_after_commit
from developers.models import Feedback
from developers.tasks import send_feedback_task


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at', 'author', 'short_message', 'status', 'task_link')
    list_filter = ('status', 'created_at')
    search_fields = ('message', 'author__username', 'author__email', 'page_url')
    readonly_fields = (
        'author', 'message', 'page_url', 'created_at',
        'status', 'task_link', 'sent_at', 'error',
    )
    fields = readonly_fields
    ordering = ('-created_at',)
    actions = ('resend',)

    def has_add_permission(self, request):
        # Messages come from the form, where the author and page are known.
        return False

    @admin.display(description='Сообщение')
    def short_message(self, obj):
        return Truncator(obj.message).chars(80)

    @admin.display(description='Задача в Bitrix24', ordering='bitrix_task_id')
    def task_link(self, obj):
        if not obj.bitrix_task_id:
            return '—'
        portal = settings.BITRIX24_PORTAL
        if not portal or not settings.BITRIX24_FEEDBACK_RESPONSIBLE_ID:
            return obj.bitrix_task_id
        url = (
            f'https://{portal}/company/personal/user/'
            f'{settings.BITRIX24_FEEDBACK_RESPONSIBLE_ID}/tasks/task/view/{obj.bitrix_task_id}/'
        )
        return format_html('<a href="{}" target="_blank" rel="noopener">#{}</a>', url, obj.bitrix_task_id)

    @admin.action(description='Отправить в Bitrix24 повторно')
    def resend(self, request, queryset):
        # Sent ones are left alone: re-sending them would open a second task.
        unsent = list(queryset.filter(~Q(status=Feedback.Status.SENT)).values_list('pk', flat=True))
        Feedback.objects.filter(pk__in=unsent).update(status=Feedback.Status.PENDING, error='')
        for pk in unsent:
            dispatch_after_commit(send_feedback_task, pk)
        skipped = queryset.count() - len(unsent)
        text = f'Поставлено в очередь на отправку: {len(unsent)}.'
        if skipped:
            text += f' Пропущено уже отправленных: {skipped}.'
        self.message_user(request, text, messages.SUCCESS if unsent else messages.WARNING)
