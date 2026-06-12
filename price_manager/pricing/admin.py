from django.contrib import admin

from .models import PriceType, PricingRule, ProductPrice, Stock


@admin.register(PriceType)
class PriceTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'label']
    search_fields = ['name', 'label']


@admin.register(PricingRule)
class PricingRuleAdmin(admin.ModelAdmin):
    list_display = ['supplier', 'source_price_type', 'dest_price_type', 'mode', 'priority', 'category']
    list_filter = ['supplier', 'mode', 'category']
    search_fields = ['supplier__name', 'source_price_type__label', 'dest_price_type__label']
    raw_id_fields = ['supplier', 'source_price_type', 'dest_price_type', 'category']


@admin.register(ProductPrice)
class ProductPriceAdmin(admin.ModelAdmin):
    list_display = ['product', 'supplier', 'price_type', 'value', 'rule', 'updated_at']
    list_filter = ['supplier', 'price_type']
    search_fields = ['product__sku', 'product__name', 'supplier__name']
    raw_id_fields = ['product', 'supplier', 'price_type', 'rule']
    readonly_fields = ['updated_at']


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ['product', 'supplier', 'quantity', 'updated_at']
    list_filter = ['supplier']
    search_fields = ['product__sku', 'product__name', 'supplier__name']
    raw_id_fields = ['product', 'supplier']
    readonly_fields = ['updated_at']
