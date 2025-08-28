from django.contrib import admin
from import_export.admin import ImportExportModelAdmin
from core.models import *
from core.resources import *


@admin.register(MainProduct)
class MainProductAdmin(ImportExportModelAdmin):
    resource_classes = [MainProductResource]
    list_display = MP_FIELDS
    search_fields = ['article', 'name', 'sku', 'stock']
    list_filter = ['supplier', 'manufacturer']  # фильтры по поставщику и производителю


@admin.register(SupplierProduct)
class SupplierProductAdmin(admin.ModelAdmin):
    list_display = MP_FIELDS
    search_fields = ['article', 'name', 'sku', 'stock']
    list_filter = ['supplier', 'manufacturer']  # фильтры по поставщику и производителю
