from django.contrib import admin

from .models import FeedMapping


@admin.register(FeedMapping)
class FeedMappingAdmin(admin.ModelAdmin):
    list_display = ['name', 'supplier', 'supplier_sku_column', 'auto_match_threshold']
    list_filter = ['supplier']
    search_fields = ['name', 'supplier__name']
