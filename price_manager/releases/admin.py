from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils.text import Truncator

from releases.models import Release


@admin.register(Release)
class ReleaseAdmin(admin.ModelAdmin):
    list_display = ('version', 'title', 'released_at', 'is_published', 'notified_at', 'short_summary')
    list_filter = ('is_published', 'released_at')
    search_fields = ('version', 'title', 'summary', 'article_html')
    fields = (
        'version', 'title', 'released_at', 'summary', 'article_html', 'markdown_copy',
        'is_published', 'notified_at', 'author', 'created_at', 'updated_at',
    )
    readonly_fields = ('markdown_copy', 'notified_at', 'author', 'created_at', 'updated_at')
    ordering = ('-released_at', '-pk')
    actions = ('publish',)

    @admin.display(description='Кратко')
    def short_summary(self, obj):
        return Truncator(obj.summary).chars(80)

    @admin.display(description='Статья (Markdown)')
    def markdown_copy(self, obj):
        if not obj.article_markdown:
            return 'Появится после сохранения — собирается из HTML автоматически.'
        return format_html(
            '<pre style="white-space: pre-wrap; max-height: 24rem; overflow: auto;">{}</pre>',
            obj.article_markdown,
        )

    def save_model(self, request, obj, form, change):
        if obj.author_id is None:
            obj.author = request.user
        announce = obj.is_published and obj.notified_at is None
        super().save_model(request, obj, form, change)
        if announce:
            self.message_user(
                request,
                f'Версия {obj.version} опубликована — оповещение уходит всем пользователям.',
                messages.SUCCESS,
            )

    @admin.action(description='Опубликовать и оповестить пользователей')
    def publish(self, request, queryset):
        # One by one through save(): that is what dispatches the notification.
        drafts = list(queryset.filter(is_published=False))
        for release in drafts:
            release.is_published = True
            release.save(update_fields=['is_published', 'updated_at'])
        skipped = len(queryset) - len(drafts)
        text = f'Опубликовано: {len(drafts)}.'
        if skipped:
            text += f' Уже опубликованы: {skipped}.'
        self.message_user(request, text, messages.SUCCESS if drafts else messages.WARNING)
