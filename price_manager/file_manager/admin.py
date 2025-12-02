from django.contrib import admin
from .models import FileModel

@admin.register(FileModel)
class FileModelAdmin(admin.ModelAdmin):
    list_display = ['id', 'file']
