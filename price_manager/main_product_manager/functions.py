from django.db import transaction
from django.db.models import Min, Max, F
from django.core.cache import cache
from django.db.models import Value, OuterRef, Subquery, Q, F, Sum
from django.utils import timezone
from django.contrib.postgres.search import SearchVectorField, SearchVector 

from .models import MainProduct, MainProductLog, MainProductDuplicate, MP_PRICES
from .tables import AVAILABLE_COLUMN_MAP, DEFAULT_VISIBLE_COLUMNS

from supplier_product_manager.models import SupplierProduct

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

def get_dupes(id, selected_compare_fields:list[str], base_queryset, once=False):
    base_queryset = base_queryset.order_by('id')
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
  
def recalculate_search_vectors(mps):
    if not mps: return None
    mps.select_related('supplier', 'category', 'manufacturer')
    def build_searchvector(mp):
      mp.search_vector=SearchVector(Value(mp._build_search_text()), config='russian')
      return mp
    mps = map(build_searchvector, mps)
    return MainProduct.objects.bulk_update(mps, fields=['search_vector'])


def update_stocks():
  query = MainProduct.objects.filter(
    pk=OuterRef('pk')
    ).prefetch_related('supplierproducts').annotate(
      new_stock=Sum(F('supplierproducts__stock'))).values('new_stock')
  mps = MainProduct.objects.prefetch_related('supplierproducts').annotate(new_stock=Subquery(query))
  mps = mps.filter(Q(stock__isnull=False)|Q(new_stock__isnull=False))
  mps = mps.filter(~Q(stock=F('new_stock')))
  mps.bulk_update(mps, fields=['stock_updated_at'])
  print(mps.values_list('stock', 'new_stock'))
  mpls = map(lambda mp: MainProductLog(main_product=mp, stock=mp.new_stock),  mps)
  MainProductLog.objects.bulk_create(mpls)
  return mps.update(stock=F('new_stock'))

def update_logs():
  updated_logs = 0
  
  for price_type in MP_PRICES:
    latest_log_price_subquery =  MainProductLog.objects.select_related('main_product').filter(
      main_product__id=OuterRef('pk')
    ).filter(price_type=price_type).order_by('-update_time').values('price')[:1]
    mps = MainProduct.objects.prefetch_related('mp_log').all().annotate(
      **{
          f'latest_log_{price_type}':Subquery(latest_log_price_subquery)
      }
    )
    mps = mps.filter(~Q(**{price_type:F(f'latest_log_{price_type}')})&
                     ((Q(**{f'{price_type}__isnull':True})&Q(**{f'latest_log_{price_type}__isnull':False}))|
                     (Q(**{f'{price_type}__isnull':False})&Q(**{f'latest_log_{price_type}__isnull':True}))))
    print(mps.values_list(price_type, f'latest_log_{price_type}'))
    mpls = map(lambda mp: MainProductLog(price_type=price_type, main_product=mp, price=getattr(mp, price_type)), mps.all())
    mpls = MainProductLog.objects.bulk_create(mpls)
    updated_logs += len(mpls)

  
  print('stock:', timezone.now())
  latest_log_stock_subquery =  MainProductLog.objects.filter(
    main_product__pk=OuterRef('pk')
  ).filter(price_type__isnull=True).order_by('-update_time').values('stock')[:1]
  mps = MainProduct.objects.filter(stock__isnull=False).annotate(
    **{
        f'latest_log_stock':Subquery(latest_log_stock_subquery)
    }
  )
  mps = mps.filter(~Q(**{'stock':F('latest_log_stock')})|Q(**{f'latest_log_stock__isnull':True}))
  mpls = map(lambda mp: MainProductLog(main_product=mp, stock=mp.stock),  mps)
  mpls = MainProductLog.objects.bulk_create(mpls)
  updated_logs += len(mpls)
  return updated_logs
