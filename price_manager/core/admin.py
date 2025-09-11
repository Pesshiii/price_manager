from django.contrib import admin
from import_export.admin import ImportExportModelAdmin
from django.contrib import admin
# from .forms import PriceManagerAdminForm
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
    list_display.append('display_discounts')
    # делаем кликабельным поле name (или id, если удобнее)
    list_display_links = ['id', 'name']
    search_fields = ['article', 'name', 'sku', 'stock']
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