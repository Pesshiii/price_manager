from django.utils.safestring import mark_safe
from django.contrib import admin
from import_export.admin import ImportExportModelAdmin
from import_export.formats.base_formats import CSV
from core.models import *
from file_manager.models import FileModel
from import_export.formats import base_formats
from core.resources import *


@admin.register(PersistentNotification)
class PersistentNotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "level", "kind", "created_at", "seen_at", "expires_at")
    list_filter = ("level", "kind", "created_at")
    search_fields = ("user__username", "message")
    ordering = ("-created_at",)


@admin.register(Bitrix24Account)
class Bitrix24AccountAdmin(admin.ModelAdmin):
    """Deleting a row unlinks the user; the next Bitrix24 login links again."""

    list_display = ("user", "bitrix_user_id", "linked_at")
    search_fields = ("user__username", "user__email", "bitrix_user_id")
    readonly_fields = ("user", "bitrix_user_id", "linked_at")
    ordering = ("-linked_at",)

    def has_add_permission(self, request):
        # Linking happens only through a Bitrix24 login, which proves the ID.
        return False


@admin.register(TaskRunHistory)
class TaskRunHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "task_name",
        "status",
        "updated_count",
        "duration_ms",
        "started_at",
        "finished_at",
    )
    list_filter = ("status", "task_name", "started_at")
    search_fields = ("task_name", "error")
    readonly_fields = (
        "task_name",
        "status",
        "updated_count",
        "duration_ms",
        "details",
        "error",
        "started_at",
        "finished_at",
        "created_at",
    )
    ordering = ("-started_at",)
