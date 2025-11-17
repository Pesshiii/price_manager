from django.contrib import admin
from django.utils.html import mark_safe
from import_export.admin import ImportExportModelAdmin
from import_export.formats import base_formats
from import_export.formats.base_formats import CSV

from common.resources import MainProductResource
from main_price.models import Category, MainProduct, Manufacturer, ManufacturerDict


class CSVWithBOM(CSV):
    """CSV в UTF-8 с BOM, чтобы Excel корректно открывал русские буквы."""

    def get_content(self, dataset, **kwargs):
        text = super().get_content(dataset, **kwargs)
        return "\ufeff" + text


@admin.register(MainProduct)
class MainProductAdmin(ImportExportModelAdmin):
    resource_class = MainProductResource

    def get_export_formats(self):
        formats = [CSVWithBOM]
        if base_formats.XLSX().can_export():
            formats.insert(0, base_formats.XLSX)
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



@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('indented_name', 'parent')
    list_display_links = ('indented_name',)
    search_fields = ('name',)
    list_filter = ('parent',)
    ordering = ('parent__id', 'name')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('parent')

    def indented_name(self, obj):
        depth = 0
        parent = obj.parent
        while parent:
            depth += 1
            parent = parent.parent
        indent = "&nbsp;" * 4 * depth + ('— ' if depth else '')
        return mark_safe(f"{indent}{obj.name}")

    indented_name.short_description = 'Категория'


@admin.register(Manufacturer)
class ManufacturerAdmin(admin.ModelAdmin):
    list_display = ['id', 'name']
    search_fields = ['name']


@admin.register(ManufacturerDict)
class ManufacturerDictAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'manufacturer']
    search_fields = ['name', 'manufacturer__name']
    list_filter = ['manufacturer']
