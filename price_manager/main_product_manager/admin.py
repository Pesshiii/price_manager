from django.utils.safestring import mark_safe
from django.contrib import admin
from django.db.models import Count
from django.db import transaction
from django.contrib import messages
from import_export.admin import ImportExportModelAdmin
from import_export.formats.base_formats import CSV
from .models import *
from file_manager.models import FileModel
from supplier_product_manager.models import SupplierProduct
from import_export.formats import base_formats
from .resources import *


class CSVWithBOM(CSV):
    """
    CSV в UTF-8 с BOM, чтобы Excel на Windows открывал русские буквы корректно.
    """
    def get_content(self, dataset, **kwargs):
        text = super().get_content(dataset, **kwargs)  # str (UTF-8)
        return "\ufeff" + text  # prepend BOM

@admin.register(MainProduct)
class MainProductAdmin(ImportExportModelAdmin):
    resource_class = MainProductResource

    # Всегда есть минимум CSV с BOM; если установлен openpyxl — будет и XLSX
    def get_export_formats(self):
        formats = [CSVWithBOM]
        if base_formats.XLSX().can_export():
            formats.insert(0, base_formats.XLSX)  # XLSX как основной
        return formats

    def get_import_formats(self):
        formats = [CSVWithBOM]
        if base_formats.XLSX().can_import():
            formats.insert(0, base_formats.XLSX)
        return formats

    list_display = [field.name for field in MainProduct._meta.fields]
    list_display_links = ['id', 'name']
    search_fields = ['article', 'name', 'sku', 'stock']
    list_filter = ['supplier', 'manufacturer']
    actions = ['resolve_conflicts']
    
    @admin.action(description="Разрешить конфликты форматирования")
    def resolve_conflicts(self, request, queryset):
      merged_groups, deleted_products, moved_supplier_products = merge_main_products_by_name(queryset)
      if merged_groups:
        messages.success(
          request,
          (
            f"Объединено {merged_groups} групп дублей. "
            f"Удалено {deleted_products} товаров главного прайса. "
            f"Перенесено {moved_supplier_products} товаров поставщиков."
          ),
        )
      else:
        messages.info(request, "Дубли по названию не найдены.")

@admin.register(MainProductLog)
class MainProductLogAdmin(admin.ModelAdmin):
    list_display = ['update_time', 'main_product__name', 'price_type', 'price', 'stock']
    search_fields = ['main_product__name']


def merge_main_products_by_name(queryset, **kwargs):
  """Объединяет продукты главного прайса с одинаковым названием."""
  duplicate_names = (
    queryset
    .values('name')
    .annotate(products_count=Count('id'))
    .filter(products_count__gt=1)
    .values_list('name', flat=True)
  )

  merged_groups = 0
  deleted_products = 0
  moved_supplier_products = 0

  with transaction.atomic():
    for name in duplicate_names:
      products = list(
        MainProduct.objects
        .filter(name=name)
        .order_by('id')
        .only('id')
      )
      if len(products) < 2:
        continue

      keep_product = products[0]
      duplicate_ids = [product.id for product in products[1:]]
      if not duplicate_ids:
        continue

      moved_supplier_products += SupplierProduct.objects.filter(
        main_product_id__in=duplicate_ids
      ).update(main_product=keep_product)
      deleted_products += MainProduct.objects.filter(id__in=duplicate_ids).delete()[0]
      merged_groups += 1

  return (merged_groups, deleted_products, moved_supplier_products)