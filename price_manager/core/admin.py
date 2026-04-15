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
    list_display = ("id", "user", "level", "created_at")
    list_filter = ("level", "created_at")
    search_fields = ("user__username", "message")
    ordering = ("-created_at",)
