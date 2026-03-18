from django.db import transaction
from django.db.models import Min

from .models import MainProduct, MainProductLog
from supplier_product_manager.models import SupplierProduct

COMPARISON_FIELD_LABELS = {
        'article': 'артиклю',
        'supplier': 'поставщику',
        'name': 'названию',
    }

def get_dupes(id, selected_compare_fields:list[str], base_queryset):
    found = False
    next_id = base_queryset.filter(id__gt=id).first().id if base_queryset.count() > 1 else None
    item = base_queryset.get(id=id)
    while not found:
        if next_id is None:
            return (next_id, None)
        buffer_queryset = base_queryset
        if 'article' in selected_compare_fields:
            buffer_queryset = buffer_queryset.filter(article=item.article)
        if 'supplier' in selected_compare_fields:
            buffer_queryset = buffer_queryset.filter(supplier=item.supplier)
        if 'name' in selected_compare_fields:
            buffer_queryset = buffer_queryset.filter(name__icontains=item.name)
        next_item = base_queryset.filter(id__gt=id).exclude(pk__in=buffer_queryset).first()
        next_id = next_item.id if next_item else None
        if buffer_queryset.filter(id__lt=id).exists() or buffer_queryset.count() == 1:
            item = next_item
            id = next_id
            continue
        base_queryset=buffer_queryset
        found = True
    return (next_id, base_queryset)



def merge_selected_main_products(selected_ids: list[int]):
  products = list(
    MainProduct.objects
    .filter(id__in=selected_ids)
    .annotate(oldest_log_at=Min('mp_log__update_time'))
    .order_by(F('oldest_log_at').asc(nulls_last=True), 'id')
  )
  if len(products) < 2:
    return None

  keep_product = products[0]
  duplicate_ids = [product.id for product in products[1:]]
  if not duplicate_ids:
    return None

  with transaction.atomic():
    moved_supplier_products = SupplierProduct.objects.filter(
      main_product_id__in=duplicate_ids
    ).update(main_product=keep_product)

    duplicate_logs = MainProductLog.objects.filter(
      main_product_id__in=duplicate_ids,
    ).values(
      'update_time',
      'price',
      'price_type',
      'stock',
    )

    moved_logs = MainProductLog.objects.bulk_create(
      [
        MainProductLog(
          update_time=log['update_time'],
          main_product=keep_product,
          price=log['price'],
          price_type=log['price_type'],
          stock=log['stock'],
        )
        for log in duplicate_logs
      ],
      ignore_conflicts=True,
    )

    deleted_products = MainProduct.objects.filter(id__in=duplicate_ids).delete()[0]

  return (keep_product, deleted_products, moved_supplier_products, len(moved_logs))
  
