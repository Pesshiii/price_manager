from django.contrib import admin

from .models import ProductPrice, ProductPriceRule, ProductPriceType


@admin.register(ProductPriceType)
class ProductPriceTypeAdmin(admin.ModelAdmin):
    list_display = ['id', 'name','show_on_page', 'sorting']


@admin.register(ProductPriceRule)
class ProductPriceRuleAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'price_type', 'source', 'markup', 'increase', 'fixed_price',
                    'priority', 'is_active']
    list_filter = ['price_type', 'is_active']
    filter_horizontal = ['categories', 'brands']
    # Товаров ~150 тыс.: виджет со списком их всех не открылся бы.
    raw_id_fields = ['products']


@admin.register(ProductPrice)
class ProductPriceAdmin(admin.ModelAdmin):
    list_display = ['product', 'price_type', 'value', 'source_value', 'rule', 'calculated_at']
    list_filter = ['price_type']
    raw_id_fields = ['product']
    readonly_fields = ['product', 'price_type', 'value', 'source_value', 'rule', 'calculated_at']
