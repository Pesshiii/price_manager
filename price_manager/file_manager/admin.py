from django.contrib import admin

from file_manager.models import FileModel


@admin.register(FileModel)
class FileModelAdmin(admin.ModelAdmin):
    list_display = ['id', 'file']
