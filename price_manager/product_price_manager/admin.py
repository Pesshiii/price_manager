from django.contrib import admin
from .models import PriceManager, UniquePriceManager

@admin.register(PriceManager)
class PriceManagerAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'supplier', 'display_discounts']
    def display_discounts(self, obj):
        return ", ".join([discount.name for discount in obj.discounts.all()])
    display_discounts.short_description = 'Категории Скидок'

@admin.register(UniquePriceManager)
class UniquePriceManagerAdmin(admin.ModelAdmin):
    list_display = ['id', 'main_products_display', 'source', 'dest', 'markup', 'increase', 'fixed_price']
    def main_products_display(self, obj):
        return ", ".join([mp.name for mp in obj.main_products.all()])
    main_products_display.short_description = 'Товары главного прайса'
