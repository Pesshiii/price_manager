from django.contrib import admin

from .models import PriceType, PricingRule


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
