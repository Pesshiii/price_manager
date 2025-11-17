from django.contrib import admin

from price_manager_app.models import PriceManager


@admin.register(PriceManager)
class PriceManagerAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'supplier']
    search_fields = ['name']
    list_filter = ['supplier']

    def display_discounts(self, obj):
        return ", ".join(discount.name for discount in obj.discounts.all())

    display_discounts.short_description = 'Категории Скидок'
