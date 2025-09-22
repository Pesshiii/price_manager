from django.utils.safestring import mark_safe
from django.contrib import admin
from import_export.admin import ImportExportModelAdmin
from import_export.formats.base_formats import CSV
from core.models import *
from import_export.formats import base_formats
from core.resources import *


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


@admin.register(SupplierProduct)
class SupplierProductAdmin(ImportExportModelAdmin):
    resource_class = SupplierProductResource
    list_display = [field.name for field in SupplierProduct._meta.fields] + ['display_discounts']
    list_display_links = ['id', 'name']
    search_fields = ['article', 'name', 'stock']
    list_filter = ['supplier', 'manufacturer']

    def display_discounts(self, obj):
        return ", ".join([discount.name for discount in obj.discounts.all()])
    display_discounts.short_description = 'Категории Скидок'

@admin.register(FileModel)
class FileModelAdmin(admin.ModelAdmin):
    list_display = ['id', 'file']

@admin.register(PriceManager)
class PriceManagerAdmin(admin.ModelAdmin):
    # form = PriceManagerAdminForm
    list_display = ['id', 'name', 'supplier', 'display_discounts']
    # autocomplete_fields = []  # можешь оставить пустым; если захочешь, подключим позже
    # def get_form(self, request, obj=None, **kwargs):
    #     """
    #     Передаём объект request в форму, чтобы она могла читать supplier из GET/POST.
    #     """
    #     Form = super().get_form(request, obj, **kwargs)
    #     class RequestAwareForm(Form):
    #         def __init__(self2, *args, **kw):
    #             kw['request'] = request
    #             super().__init__(*args, **kw)
    #     return RequestAwareForm
    def display_discounts(self, obj):
        return ", ".join([discount.name for discount in obj.discounts.all()])
    display_discounts.short_description = 'Категории Скидок'


@admin.register(Discount)
class DiscountAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'supplier']
    list_filter = ['supplier']
    search_fields = ['name']


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("indented_name", "parent")
    list_display_links = ("indented_name",)
    search_fields = ("name",)
    list_filter = ("parent",)
    ordering = ("parent__id", "name")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("parent")

    def indented_name(self, obj):
        # считаем глубину по parent (у вас иерархия через FK на себя)
        depth = 0
        p = obj.parent
        while p:
            depth += 1
            p = p.parent
        indent = "&nbsp;" * 4 * depth + ("— " if depth else "")
        return mark_safe(f"{indent}{obj.name}")
    indented_name.short_description = "Категория"