from django.contrib import admin
from .models import SupplierProduct, SupplierFile


@admin.register(SupplierProduct)
class SupplierProductAdmin(admin.ModelAdmin):
    # показываем все поля модели
    list_display = [field.name for field in SupplierProduct._meta.fields]
    # делаем кликабельным поле name (или id, если удобнее)
    list_display_links = ['id', 'name']
    search_fields = ['article', 'name', 'stock']
    list_filter = ['supplier', 'manufacturer']

@admin.register(SupplierFile)
class SupplierFileAdmin(admin.ModelAdmin):
    # показываем все поля модели
    list_display = ['pk', 'setting', 'status', 'logs']