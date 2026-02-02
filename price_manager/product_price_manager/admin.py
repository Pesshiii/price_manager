from django.contrib import admin
from .models import PriceManager, PriceTag

@admin.register(PriceManager)
class PriceManagerAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'supplier', 'display_discounts']
    def display_discounts(self, obj):
        return ", ".join([discount.name for discount in obj.discounts.all()])
    display_discounts.short_description = 'Категории Скидок'


@admin.register(PriceTag)
class UniquePriceManagerAdmin(admin.ModelAdmin):
    list_display = ['mp', 'source', 'dest', 'markup', 'increase', 'fixed_price']
