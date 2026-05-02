from django.utils.safestring import mark_safe
from django.contrib import admin
from import_export.admin import ImportExportModelAdmin
from import_export.formats.base_formats import CSV
from core.models import *
from import_export.formats import base_formats
from core.resources import *


@admin.register(PersistentNotification)
class PersistentNotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "level", "created_at")
    list_filter = ("level", "created_at")
    search_fields = ("user__username", "message")
    ordering = ("-created_at",)


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
