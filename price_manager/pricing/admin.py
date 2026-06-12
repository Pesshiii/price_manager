from django.contrib import admin

from .models import PriceType


@admin.register(PriceType)
class PriceTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'label']
    search_fields = ['name', 'label']
