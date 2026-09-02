from django.contrib import admin
from mptt.admin import DraggableMPTTAdmin

from .models import Category, Product


@admin.register(Category)
class CategoryAdmin(DraggableMPTTAdmin):
    list_display = ('tree_actions', 'indented_title', 'slug', 'pim_id')
    search_fields = ('name', 'slug', 'pim_id')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('number', 'name', 'pim_id', 'category_path', 'updated_at')
    search_fields = ('number', 'name', 'pim_id')
    filter_horizontal = ('categories',)
    readonly_fields = ('raw_data', 'category_path', 'created_at', 'updated_at')
