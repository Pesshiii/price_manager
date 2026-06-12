from django.contrib import admin

from .models import FeedColumnMapping, FeedMapping


@admin.register(FeedMapping)
class FeedMappingAdmin(admin.ModelAdmin):
    list_display = ['name', 'supplier', 'supplier_sku_column', 'auto_match_threshold']
    list_filter = ['supplier']
    search_fields = ['name', 'supplier__name']


@admin.register(FeedColumnMapping)
class FeedColumnMappingAdmin(admin.ModelAdmin):
    list_display = ['feed_mapping', 'column_name', 'role', 'price_type']
    list_filter = ['role', 'feed_mapping__supplier']
    search_fields = ['column_name']
    autocomplete_fields = ['price_type']  # requires PriceType to have search_fields in admin
