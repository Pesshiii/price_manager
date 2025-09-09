from django.contrib import admin
from import_export.admin import ImportExportModelAdmin
from core.models import *
from core.resources import *


@admin.register(MainProduct)
class MainProductAdmin(ImportExportModelAdmin):
    resource_classes = [MainProductResource]
    # показываем все поля модели
    list_display = [field.name for field in MainProduct._meta.fields]
    # делаем кликабельным поле name (или id, если удобнее)
    list_display_links = ['id', 'name']
    search_fields = ['article', 'name', 'sku', 'stock']
    list_filter = ['supplier', 'manufacturer']


@admin.register(SupplierProduct)
class SupplierProductAdmin(admin.ModelAdmin):
    # показываем все поля модели
    list_display = [field.name for field in SupplierProduct._meta.fields]
    # делаем кликабельным поле name (или id, если удобнее)
    list_display_links = ['id', 'name']
    search_fields = ['article', 'name', 'sku', 'stock']
    list_filter = ['supplier', 'manufacturer']

@admin.register(FileModel)
class FileModelAdmin(admin.ModelAdmin):
    list_display = ['id', 'file']

@admin.register(PriceManager)
class PriceManagerAdmin(admin.ModelAdmin):
    list_display = ['id', 'name']

@admin.register(Discount)
class DiscountAdmin(admin.ModelAdmin):
    list_display = ['id', 'name']