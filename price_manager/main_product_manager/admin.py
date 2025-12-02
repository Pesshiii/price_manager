from django.utils.safestring import mark_safe
from django.contrib import admin
from import_export.admin import ImportExportModelAdmin
from import_export.formats.base_formats import CSV
from .models import *
from file_manager.models import FileModel
from import_export.formats import base_formats
from .resources import *


class CSVWithBOM(CSV):
    """
    CSV в UTF-8 с BOM, чтобы Excel на Windows открывал русские буквы корректно.
    """
    def get_content(self, dataset, **kwargs):
        text = super().get_content(dataset, **kwargs)  # str (UTF-8)
        return "\ufeff" + text  # prepend BOM

@admin.register(MainProduct)
class MainProductAdmin(ImportExportModelAdmin):
    resource_class = MainProductResource

    # Всегда есть минимум CSV с BOM; если установлен openpyxl — будет и XLSX
    def get_export_formats(self):
        formats = [CSVWithBOM]
        if base_formats.XLSX().can_export():
            formats.insert(0, base_formats.XLSX)  # XLSX как основной
        return formats

    def get_import_formats(self):
        formats = [CSVWithBOM]
        if base_formats.XLSX().can_import():
            formats.insert(0, base_formats.XLSX)
        return formats

    list_display = [field.name for field in MainProduct._meta.fields]
    list_display_links = ['id', 'name']
    search_fields = ['article', 'name', 'sku', 'stock']
    list_filter = ['supplier', 'manufacturer']
