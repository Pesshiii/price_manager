
from django.db import transaction
from django.db.models import Min, Max, F
from .models import MainProduct, MainProductLog
from supplier_product_manager.models import SupplierProduct
from django.core.cache import cache
from .tables import AVAILABLE_COLUMN_MAP, DEFAULT_VISIBLE_COLUMNS

CACHE_TTL = 60 * 60 * 24 * 30  # 30 дней

def _cache_key(user_id: int) -> str:
    return f"mainprice:selected_columns:user:{user_id}"

def normalize_columns(columns):
    valid = [col for col in columns if col in AVAILABLE_COLUMN_MAP]
    return valid or DEFAULT_VISIBLE_COLUMNS

def save_user_columns(user, columns):
    if not user.is_authenticated:
        return
    cache.set(_cache_key(user.id), normalize_columns(columns), CACHE_TTL)

def load_user_columns(user):
    if not user.is_authenticated:
        return DEFAULT_VISIBLE_COLUMNS
    return cache.get(_cache_key(user.id), DEFAULT_VISIBLE_COLUMNS)

COMPARISON_FIELD_LABELS = {
        'article': 'артиклю',
        'supplier': 'поставщику',
        'name': 'названию',
    }

def get_dupes(id, selected_compare_fields:list[str], base_queryset, once=False):
    next_id = base_queryset.filter(id__gt=id).first().id if base_queryset.filter(id__gt=id).exists() else None
    item = base_queryset.get(id=id)
    for i in range(MainProduct.objects.count()):
        if next_id is None:
            return (next_id, None)
        buffer_queryset = base_queryset
        if 'article' in selected_compare_fields:
            buffer_queryset = buffer_queryset.filter(article=item.article)
        if 'supplier' in selected_compare_fields:
            buffer_queryset = buffer_queryset.filter(supplier=item.supplier)
        if 'name' in selected_compare_fields:
            buffer_queryset = buffer_queryset.filter(name__icontains=item.name)
        if once:
            return (None, buffer_queryset)
        next_item = base_queryset.filter(id__gt=id).exclude(pk__in=buffer_queryset).first()
        next_id = next_item.id if next_item else None
        if buffer_queryset.count() == 1:
            item = next_item
            id = next_id
            continue
        if buffer_queryset.filter(id__lt=id).exists():
            for product in buffer_queryset.filter(id__lt=id):
                included = False
                if id in get_dupes(product.id, selected_compare_fields, base_queryset, once=True)[1].values_list('id', flat=True):
                    item = next_item
                    id = next_id
                    included = True
                    break
            if included:
                continue
        return (next_id, buffer_queryset)
    return (next_id, None)



def merge_selected_main_products(selected_ids: list[int], keep_product_id: int | None = None):
    products = (MainProduct.objects
        .filter(id__in=selected_ids)
        .annotate(oldest_log_at=Min('mp_log__update_time'))
        .order_by(F('oldest_log_at').asc(nulls_last=True), 'id'))
    if products.count() < 2:
        return None
    
    if keep_product_id is None:
        keep_product = products.first()
    else:
        keep_product = products.filter(id=keep_product_id).first()
        if keep_product is None:
            return None
    
    with transaction.atomic():
        moved_supplier_products = SupplierProduct.objects.exclude(
        main_product__id=keep_product.id
        ).filter(main_product__id__in=products.exclude(id=keep_product.id)).update(main_product=keep_product)
        
        moved_logs = (MainProductLog
                      .objects.select_related('main_product')
                      .filter(main_product__id__in=selected_ids)
                      .exclude(main_product=keep_product).update(main_product=keep_product))
        
        deleted_products, _ = products.exclude(id=keep_product.id).delete()

    
    return (keep_product, deleted_products, moved_supplier_products, moved_logs)
  
