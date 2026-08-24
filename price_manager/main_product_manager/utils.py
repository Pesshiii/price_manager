import time

import httpx
from django.db import transaction
from django.db.models import Min, Max, F
from django.core.cache import cache
from django.db.models import Value, OuterRef, Subquery, Q, F, Sum, IntegerField
from django.utils import timezone
from django.contrib.postgres.search import SearchVectorField, SearchVector
from django.db.models.functions import Coalesce
from django.conf import settings

from .models import MainProduct, MainProductLog, MP_PRICES
from .pim_api import site, EntityList, Entity, Where, FileRecord
from .columns import AVAILABLE_COLUMN_MAP, DEFAULT_VISIBLE_COLUMNS

from supplier_product_manager.models import SupplierProduct
from supplier_manager.models import Category, Manufacturer

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


def _fetch_pim_product(pim_id: str) -> tuple[dict | None, bool]:
    """Fetch a verified PIM `Product` (master record) by id straight from the API (no cache).

    pim_id is the id of the verified/merged PIM `Product`, not a `ContributorProduct` —
    see _search_pim_id for how it's resolved via ContributorProduct.masterRecordId.

    Returns (data, not_found) — not_found is True only on an explicit 404,
    so callers can tell "PIM deleted/renumbered this id" apart from a
    transient network/API error.
    """
    t0 = time.monotonic()
    try:
        data = site.get(Entity(name='Product', id=pim_id))
        return data, False
    except httpx.HTTPStatusError as exc:
        _record_pim_error("get_pim_data", exc, int((time.monotonic() - t0) * 1000))
        return None, exc.response.status_code == 404
    except Exception as exc:
        _record_pim_error("get_pim_data", exc, int((time.monotonic() - t0) * 1000))
        return None, False


def _queue_pim_population(pim_id: str) -> None:
    """Enqueue the background relation-sync task for a pim_id whose data isn't cached yet.

    Deduped via a short-lived cache flag (cache.add is atomic) so a burst of cache
    misses for the same pim_id — e.g. rendering a product list — only fires one task.
    """
    queued_key = f"pim_populate_queued:{pim_id}"
    if not cache.add(queued_key, True, _PIM_POPULATE_QUEUED_TTL):
        return
    from .tasks import populate_pim_relations_task
    populate_pim_relations_task.delay(pim_id)


def get_pim_data(pim_id: str | None, refresh: bool = False) -> dict | None:
    if not pim_id:
        return None
    cache_key = f"pim_product:{pim_id}"
    if not refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        _queue_pim_population(pim_id)
    data, not_found = _fetch_pim_product(pim_id)
    if data is not None:
        cache.set(cache_key, data, PIM_CACHE_TTL)
        return data
    if not_found:
        cache.delete(cache_key)
        return None
    return cache.get(cache_key)


_PIM_NO_MATCH_TTL = 60 * 60 * 4  # 4 hours — avoid hammering PIM for unlinked products
_PIM_POPULATE_QUEUED_TTL = 60 * 10  # throttle for the cache-miss population trigger


def _search_pim_id(product) -> str | None:
    """Resolve a MainProduct's pim_id: the verified PIM `Product` (master record) id.

    A product isn't directly linked to a `Product` — it's found by searching
    `ContributorProduct` (by priceManagerId, then by sku/number) and reading its
    `masterRecordId`, which points at the merged/verified `Product`. A
    ContributorProduct without a masterRecordId yet (not verified in PIM) counts
    as no match.

    Throttled by a no-match cache (_PIM_NO_MATCH_TTL) so unmatched products
    are only retried periodically instead of on every lookup/task run.
    Does not persist the result — callers decide how/when to save it.
    """
    no_match_key = f"pim_no_match:{product.pk}"
    if cache.get(no_match_key):
        return None

    searches = [Where(attribute='priceManagerId', type='like', value=str(product.pk))]
    if product.sku:
        searches.append(Where(attribute='number', type='like', value=product.sku))

    for where in searches:
        t0 = time.monotonic()
        try:
            result = site.get(
                EntityList(name='ContributorProduct', select=['masterRecordId'], where=[where])
            )
            for item in result.get('list', []):
                master_record_id = item.get('masterRecordId')
                if master_record_id:
                    return master_record_id
            # No match is normal — don't treat as error, just set no-match cache below
        except Exception as exc:
            _record_pim_error("_search_pim_id", exc, int((time.monotonic() - t0) * 1000))

    cache.set(no_match_key, True, _PIM_NO_MATCH_TTL)
    return None


def _resolve_pim_id(product) -> str | None:
    """Look up pim_id in PIM and persist it on the product if found."""
    pim_id = _search_pim_id(product)
    if pim_id:
        MainProduct.objects.filter(pk=product.pk).update(pim_id=pim_id)
        product.pim_id = pim_id
    return pim_id


def get_pim_data_for_product(product, refresh: bool = False) -> dict | None:
    """Return PIM data for a MainProduct, resolving pim_id if not set.

    If the stored pim_id comes back 404 (deleted/renumbered in PIM), the
    stale link is cleared and re-resolved by priceManagerId/name before
    retrying once.
    """
    if not product.pim_id:
        _resolve_pim_id(product)
    if not product.pim_id:
        return None
    cache_key = f"pim_product:{product.pim_id}"
    if not refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        _queue_pim_population(product.pim_id)
    data, not_found = _fetch_pim_product(product.pim_id)
    if data is not None:
        cache.set(cache_key, data, PIM_CACHE_TTL)
        return data
    if not not_found:
        return cache.get(cache_key)

    MainProduct.objects.filter(pk=product.pk).update(pim_id=None)
    cache.delete(cache_key)
    product.pim_id = None
    cache.delete(f"pim_no_match:{product.pk}")
    if not _resolve_pim_id(product):
        return None
    data, _ = _fetch_pim_product(product.pim_id)
    if data is not None:
        cache.set(f"pim_product:{product.pim_id}", data, PIM_CACHE_TTL)
    return data


def _resolve_manufacturer(data: dict) -> Manufacturer | None:
    """Find or create the Manufacturer matching a PIM Product's brandId/brandName."""
    brand_id = data.get('brandId')
    if not brand_id:
        return None
    manufacturer = Manufacturer.objects.filter(pim_id=brand_id).first()
    if manufacturer:
        return manufacturer
    brand_name = data.get('brandName') or brand_id
    manufacturer, created = Manufacturer.objects.get_or_create(
        name=brand_name, defaults={'pim_id': brand_id}
    )
    if not created and not manufacturer.pim_id:
        manufacturer.pim_id = brand_id
        manufacturer.save(update_fields=['pim_id'])
    return manufacturer


def sync_pim_relations(pim_id: str, data: dict) -> int:
    """Sync manufacturer + categories for every MainProduct linked to this PIM Product id.

    Several MainProducts (from different suppliers) can share the same pim_id, since
    it now points at a verified/merged PIM `Product` rather than a per-supplier
    ContributorProduct — so this updates all of them in one go.
    """
    products = list(MainProduct.objects.filter(pim_id=pim_id))
    if not products:
        return 0

    manufacturer = _resolve_manufacturer(data)
    if manufacturer:
        MainProduct.objects.filter(pim_id=pim_id).update(manufacturer=manufacturer)

    category_ids = data.get('categoriesIds') or []
    categories = list(Category.objects.filter(pim_id__in=category_ids)) if category_ids else []
    if categories:
        through = MainProduct.categories.through
        through.objects.filter(mainproduct__in=products).delete()
        through.objects.bulk_create(
            [through(mainproduct=p, category=c) for p in products for c in categories],
            ignore_conflicts=True,
        )
    return len(products)


def prefetch_pim_data(products) -> dict:
    """Fetch PIM data for a list of MainProduct objects and return {product.pk: data}.

    Resolves pim_id on the fly for products that don't have one yet (guarded by
    a 4-hour no-match cache so PIM isn't hammered for unlinked products).
    """
    result = {}
    for product in products:
        if not product.pim_id:
            _resolve_pim_id(product)
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
    return "https://" + data.get(f'{size}ThumbnailUrl') or data.get('url') or data.get('downloadUrl')



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
    mps.select_related('supplier', 'manufacturer')
    def build_searchvector(mp):
      mp.search_vector = mp._build_searchvector()
      return mp
    mps = map(build_searchvector, mps)
    return MainProduct.objects.bulk_update(mps, fields=['search_vector'])


def update_stocks():
    stock_subq = (
        SupplierProduct.objects
        .filter(main_product_id=OuterRef('pk'))
        .order_by('-updated_at')
        .values('stock')[:1]
    )
    mps = MainProduct.objects.annotate(
        new_stock=Coalesce(Subquery(stock_subq, output_field=IntegerField()), Value(0), output_field=IntegerField()),
        current_stock_safe=Coalesce('stock', Value(0), output_field=IntegerField()),
    ).filter(~Q(current_stock_safe=F('new_stock')))
    mpls = [MainProductLog(main_product=mp, stock=mp.new_stock) for mp in mps]
    MainProductLog.objects.bulk_create(mpls)
    return mps.update(stock=F('new_stock'), stock_updated_at=timezone.now())

def create_pim_links(delay: float = 0.5) -> int:
    products = list(MainProduct.objects.filter(pim_id__isnull=True)[:1000])
    result = []
    for product in products:
        pim_id = _search_pim_id(product)
        if pim_id:
            product.pim_id = pim_id
            result.append(product)
        time.sleep(delay)
    # bulk_update is the only DB write; kept outside the API loop so
    # execute_locked_task's transaction.atomic() doesn't span HTTP calls.
    if result:
        MainProduct.objects.bulk_update(result, fields=['pim_id'])
    return len(result)


def reindex_pim_ids(delay: float = 0.5, batch_size: int | None = None) -> int:
    """Re-resolve pim_id for ALL MainProducts, including ones already linked.

    Unlike create_pim_links (which only fills pim_id__isnull=True), this
    re-searches PIM for every product so relinked/re-merged records pick up
    their new pim_id. Only writes products whose resolved pim_id changed.
    """
    queryset = MainProduct.objects.all().order_by('pk')
    if batch_size:
        queryset = queryset[:batch_size]
    products = list(queryset)
    result = []
    for product in products:
        pim_id = _search_pim_id(product)
        if pim_id and pim_id != product.pim_id:
            product.pim_id = pim_id
            result.append(product)
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