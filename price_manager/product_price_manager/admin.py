from django.contrib import admin
from .models import PriceManager, PriceTag

@admin.register(PriceManager)
class PriceManagerAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'supplier', 'display_discounts']
    def display_discounts(self, obj):
        return ", ".join([discount.name for discount in obj.discounts.all()])
    display_discounts.short_description = 'Категории Скидок'

    def save_model(self, request, obj, form, change):
        # Ценники — после M2M (save_related): от охвата они и зависят.
        obj.save(sync_pricetags=False)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        form.instance.sync_pricetags()


@admin.register(PriceTag)
class PriceTagAdmin(admin.ModelAdmin):
    list_display = ['mp', 'p_manager', 'source', 'dest', 'markup', 'increase', 'fixed_price']
