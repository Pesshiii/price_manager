from django.contrib import admin
from dataframe.models import FileModel

@admin.register(FileModel)
class FileModelAdmin(admin.ModelAdmin):
    list_display = ("id", "file")