from django.contrib import admin
from .models import Discount, Category, Manufacturer
from main_product_manager.models import MainProduct
from django.utils.safestring import mark_safe
from django.contrib.postgres.search import SearchQuery
from django.contrib import messages
import re

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


@admin.register(Manufacturer)
class ManufacturerAdmin(admin.ModelAdmin):
    list_display = ['id', 'name']
    list_filter = ['name']
    search_fields = ['name']
    actions = ['resolve_manufacturer']

    def _build_partial_query(self, value):
      value = re.sub(r"[^\w\-\\\/]+", " ", value, flags=re.UNICODE)
      terms = [bit for bit in value.split() if bit]
      if not terms:
        return None
      query = SearchQuery('')
      for term in terms:
        query &= SearchQuery(f'{term}:*', search_type='raw', config='russian')
      return query
    @admin.action(description="Добавить производителя в ГП")
    def resolve_manufacturer(self, request, queryset):
        updated = 0
        for man in queryset:
            query = self._build_partial_query(man.name)
            if query is None:
                return queryset
            updated += MainProduct.objects.filter(search_vector=query).update(manufacturer=man)
        messages.info(request, f'Обновлено товаров: {updated}')