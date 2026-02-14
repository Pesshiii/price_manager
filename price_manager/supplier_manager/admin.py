from django.contrib import admin
from .models import Discount, Category
from django.utils.safestring import mark_safe

@admin.register(Discount)
class DiscountAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'supplier']
    list_filter = ['supplier']
    search_fields = ['name']


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("indented_name", "parent")
    list_display_links = ("indented_name",)
    search_fields = ("name",)
    list_filter = ("parent",)
    ordering = ("parent__id", "name")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("parent")

    def indented_name(self, obj):
        # считаем глубину по parent (у вас иерархия через FK на себя)
        depth = 0
        p = obj.parent
        while p:
            depth += 1
            p = p.parent
        indent = "&nbsp;" * 4 * depth + ("— " if depth else "")
        return mark_safe(f"{indent}{obj.name}")
    indented_name.short_description = "Категория"