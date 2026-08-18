import time

from django.db import transaction
from django.db.models import Min, Max, F
from django.core.cache import cache
from django.db.models import Value, OuterRef, Subquery, Q, F, Sum, IntegerField
from django.utils import timezone
from django.contrib.postgres.search import SearchVectorField, SearchVector
from django.db.models.functions import Coalesce
from django.conf import settings

from .models import MainProduct, MainProductLog, MP_PRICES
from .pim_api import site, EntityList, Where, ProductPM, FileRecord
from .columns import AVAILABLE_COLUMN_MAP, DEFAULT_VISIBLE_COLUMNS

from supplier_product_manager.models import SupplierProduct

CACHE_TTL = 60 * 60 * 24 * 30  # 30 дней
PIM_CACHE_TTL = 60 * 60 * 24  # 24 часа

_PIM_LAST_ERROR_KEY = "pim_last_error"
_PIM_NOTIF_THROTTLE_PREFIX = "pim_notif_sent:"
_PIM_NOTIF_THROTTLE_TTL = 60 * 30  # 30 minutes between repeat notifications


def _record_pim_error(op: str, exc: Exception, elapsed_ms: int) -> None:
    from django.utils import timezone
    cache.set(_PIM_LAST_ERROR_KEY, {
        "op": op,
        "error": f"{type(exc).__name__}: {exc}",
        "elapsed_ms": elapsed_ms,
        "at": timezone.now().strftime("%d.%m.%Y %H:%M:%S"),
    }, timeout=60 * 60)


def maybe_notify_pim_error(user) -> None:
    """Create one throttled PersistentNotification per error window when PIM is failing."""
    if not user or not user.is_authenticated:
        return
    error_info = cache.get(_PIM_LAST_ERROR_KEY)
    if not error_info:
        return
    throttle_key = f"{_PIM_NOTIF_THROTTLE_PREFIX}{user.pk}"
    if cache.get(throttle_key):
        return
    from core.models import PersistentNotification
    PersistentNotification.objects.create(
        user=user,
        level="danger",
        message=(
            f"PIM недоступен [{error_info['op']}]: "
            f"{error_info['error']} — "
            f"{error_info['elapsed_ms']}ms в {error_info['at']}"
        ),
    )
    cache.set(throttle_key, True, _PIM_NOTIF_THROTTLE_TTL)


def get_pim_data(pim_id: str | None) -> dict | None:
    if not pim_id:
        return None
    cache_key = f"pim:{pim_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    t0 = time.monotonic()
    try:
        data = site.get(ProductPM(id=pim_id))
        cache.set(cache_key, data, PIM_CACHE_TTL)
        return data
    except Exception as exc:
        _record_pim_error("get_pim_data", exc, int((time.monotonic() - t0) * 1000))
        return None


_PIM_NO_MATCH_TTL = 60 * 60 * 4  # 4 hours — avoid hammering PIM for unlinked products


def _resolve_pim_id(product) -> str | None:
    """Look up pim_id in PIM by priceManagerId and persist it if found."""
    no_match_key = f"pim_no_match:{product.pk}"
    if cache.get(no_match_key):
        return None
    t0 = time.monotonic()
    try:
        result = site.get(
            EntityList(
                name='ProductPM',
                select=['id'],
                where=[Where(attribute='priceManagerId', type='like', value=str(product.pk))],
            )
        )
        if result.get('list'):
            pim_id = result['list'][0]['id']
            MainProduct.objects.filter(pk=product.pk).update(pim_id=pim_id)
            product.pim_id = pim_id
            return pim_id
        # No match is normal — don't treat as error, just set no-match cache below
    except Exception as exc:
        _record_pim_error("_resolve_pim_id", exc, int((time.monotonic() - t0) * 1000))
    cache.set(no_match_key, True, _PIM_NO_MATCH_TTL)
    return None


def get_pim_data_for_product(product) -> dict | None:
    """Return PIM data for a MainProduct, resolving pim_id if not set."""
    if not product.pim_id:
        _resolve_pim_id(product)
    return get_pim_data(product.pim_id)


def prefetch_pim_data(products) -> dict:
    """Fetch PIM data for a list of MainProduct objects and return {product.pk: data}.

    Only fetches data for products that already have pim_id — resolution is done
    by the create_pim_links Celery task to avoid blocking page loads.
    """
    result = {}
    for product in products:
        if not product.pim_id:
            continue
        data = get_pim_data(product.pim_id)
        if data:
            result[product.pk] = data
    return result


def get_file_url(file_id: str | None, size: str = 'medium') -> str | None:
    """Return a thumbnail URL for a PIM File record. size: 'small', 'medium', 'large'."""
    if not file_id:
        return None
    cache_key = f"pim_file:{file_id}"
    data = cache.get(cache_key)
    if data is None:
        t0 = time.monotonic()
        try:
            data = site.get(FileRecord(id=file_id))
            cache.set(cache_key, data, PIM_CACHE_TTL)
        except Exception as exc:
            _record_pim_error("get_file_url", exc, int((time.monotonic() - t0) * 1000))
            return None
    return settings.PIM_HOST + data.get(f'{size}ThumbnailUrl') or data.get('url') or data.get('downloadUrl')



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
            included = False
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
      mp.search_vector = mp._build_searchvector()
      return mp
    mps = map(build_searchvector, mps)
    return MainProduct.objects.bulk_update(mps, fields=['search_vector'])


def update_stocks():
  query = MainProduct.objects.filter(
    pk=OuterRef('pk')
    ).prefetch_related('supplierproducts').annotate(
      new_stock=Coalesce(Sum(F('supplierproducts__stock')), Value(0), output_field=IntegerField())
    ).values('new_stock')
  mps = MainProduct.objects.prefetch_related('supplierproducts').annotate(
    new_stock=Subquery(query, output_field=IntegerField())
  )
  mps = mps.annotate(
    current_stock_safe=Coalesce('stock', Value(0), output_field=IntegerField())
  ).filter(~Q(current_stock_safe=F('new_stock')))
  mps.bulk_update(mps, fields=['stock_updated_at'])
  print(mps.values_list('stock', 'new_stock'))
  mpls = map(lambda mp: MainProductLog(main_product=mp, stock=mp.new_stock),  mps)
  MainProductLog.objects.bulk_create(mpls)
  return mps.update(stock=F('new_stock'))

def create_pim_links(delay: float = 0.5) -> int:
    products = list(MainProduct.objects.filter(pim_id__isnull=True)[:1000])
    result = []
    for product in products:
        try:
            pim_list = site.get(
                EntityList(
                    name='ProductPM',
                    select=['id'],
                    where=[Where(attribute='priceManagerId', type='like', value=str(product.id))],
                )
            )
            if pim_list.get('list'):
                product.pim_id = pim_list['list'][0]['id']
                result.append(product)
        except Exception:
            pass
        time.sleep(delay)
    # bulk_update is the only DB write; kept outside the API loop so
    # execute_locked_task's transaction.atomic() doesn't span HTTP calls.
    if result:
        MainProduct.objects.bulk_update(result, fields=['pim_id'])
    return len(result)


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