from django.contrib import admin
from mptt.admin import DraggableMPTTAdmin

from .models import Brand, Category, CharacteristicType, Product


@admin.register(Category)
class CategoryAdmin(DraggableMPTTAdmin):
    list_display = ('tree_actions', 'indented_title', 'slug')
    search_fields = ('name', 'slug')


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug')
    search_fields = ('name', 'slug')


@admin.register(CharacteristicType)
class CharacteristicTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'label', 'value_type', 'unit', 'required')
    list_filter = ('value_type', 'required')
    filter_horizontal = ('categories',)
    search_fields = ('name', 'label')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('sku', 'name', 'category', 'brand', 'status', 'updated_at')
    list_filter = ('status', 'category', 'brand')
    search_fields = ('sku', 'name')
    autocomplete_fields = ('category', 'brand')
