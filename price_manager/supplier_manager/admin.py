from django.contrib import admin

from supplier_manager.models import Currency, Discount, Supplier, SupplierProduct


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'price_updated_at', 'stock_updated_at']
    search_fields = ['name']


@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'value']
    search_fields = ['name']


@admin.register(Discount)
class DiscountAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'supplier']
    list_filter = ['supplier']
    search_fields = ['name']


@admin.register(SupplierProduct)
class SupplierProductAdmin(admin.ModelAdmin):
    list_display = [field.name for field in SupplierProduct._meta.fields] + ['display_discounts']
    list_display_links = ['id', 'name']
    search_fields = ['article', 'name', 'sku', 'stock']
    list_filter = ['supplier', 'manufacturer']

    def display_discounts(self, obj):
        return ', '.join(discount.name for discount in obj.discounts.all())

    display_discounts.short_description = 'Категории Скидок'
