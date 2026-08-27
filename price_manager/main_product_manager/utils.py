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
from .pim_api import site, EntityList, Entity, Where, FileRecord, upsert_async
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
    if not settings.DEBUG:
        return
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


_PIM_404_COUNT_PREFIX = "pim_404_count:"
_PIM_404_THRESHOLD = 3  # consecutive 404s before we treat pim_id as dead
_PIM_404_COUNT_TTL = 60 * 60 * 24  # window resets if failures aren't consecutive-ish


def _note_pim_404(pim_id: str) -> None:
    """Track a 404 for a pim_id; once _PIM_404_THRESHOLD is hit in a row,
    clear pim_id from every MainProduct pointing at it so renders stop
    hammering a dead id — create_pim_links/reindex_pim_ids will re-link it.
    """
    count_key = f"{_PIM_404_COUNT_PREFIX}{pim_id}"
    count = cache.get(count_key, 0) + 1
    if count < _PIM_404_THRESHOLD:
        cache.set(count_key, count, _PIM_404_COUNT_TTL)
        return
    cache.delete(count_key)
    MainProduct.objects.filter(pim_id=pim_id).update(pim_id=None)


def _note_pim_success(pim_id: str) -> None:
    cache.delete(f"{_PIM_404_COUNT_PREFIX}{pim_id}")


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
        _note_pim_success(pim_id)
        return data
    if not_found:
        cache.delete(cache_key)
        _note_pim_404(pim_id)
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

    searches = [Where(attribute='number', type='like', value=product.sku)]

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

    If the stored pim_id 404s _PIM_404_THRESHOLD times in a row (deleted/
    renumbered in PIM), get_pim_data clears it from the DB — detected here via
    refresh_from_db — and it's re-resolved by priceManagerId/sku before
    retrying once.
    """
    if not product.pim_id:
        _resolve_pim_id(product)
    if not product.pim_id:
        return None
    data = get_pim_data(product.pim_id, refresh=refresh)
    if data is not None:
        return data

    product.refresh_from_db(fields=['pim_id'])
    if product.pim_id:
        return None  # still linked — transient error or under the 404 threshold

    cache.delete(f"pim_no_match:{product.pk}")
    if not _resolve_pim_id(product):
        return None
    return get_pim_data(product.pim_id, refresh=refresh)


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


def _fetch_pim_category(pim_category_id: str) -> dict | None:
    t0 = time.monotonic()
    try:
        return site.get(Entity(name='Category', id=pim_category_id))
    except Exception as exc:
        _record_pim_error("_ensure_pim_category", exc, int((time.monotonic() - t0) * 1000))
        return None


def _ensure_pim_category(pim_category_id: str) -> Category | None:
    """Find or create the local Category matching a PIM category id.

    Walks up `parentsIds[0]` (the immediate parent — the local Category tree only
    supports a single parent) creating any missing ancestors too, so the full
    branch ends up marked in the tree. Each newly created/linked category gets its
    search_vector (re)built. Returns None if the category can't be resolved (PIM
    error) rather than risk misplacing it under the wrong parent.
    """
    if not pim_category_id:
        return None
    category = Category.objects.filter(pim_id=pim_category_id).first()
    if category:
        return category

    data = _fetch_pim_category(pim_category_id)
    if not data:
        return None

    parent_ids = data.get('parentsIds') or []
    parent = None
    if parent_ids:
        parent = _ensure_pim_category(parent_ids[0])
        if parent is None:
            return None

    category, created = Category.objects.get_or_create(
        parent=parent, name=data.get('name') or pim_category_id,
        defaults={'pim_id': pim_category_id},
    )
    if not created and not category.pim_id:
        category.pim_id = pim_category_id
        category.save(update_fields=['pim_id'])
    if created or category.search_vector is None:
        category.rebuild_search_vector()
    return category


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
    categories = [c for c in (_ensure_pim_category(cid) for cid in category_ids) if c]
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

    Table rendering never resolves/reindexes pim_id — that's the job of the
    background tasks (create_pim_links, reindex_pim_ids). A product without a
    pim_id, or whose pim_id 404s with nothing cached, is simply skipped here
    rather than triggering a live PIM search.
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

PIM_PRODUCT_ENTITY = 'PriceManagerProduct'


def compute_supplier_sku(article: str, supplier) -> str:
    """The MainProduct.sku a SupplierProduct.article turns into once copied to
    MainProduct (copy_supplier_products_to_main_task) — prefixed/suffixed per
    supplier.sku_type/sku_value. Centralized so PIM pushes for SupplierProduct
    (pre-copy) and MainProduct (post-copy) agree on the same `number` and
    don't create two separate PriceManagerProduct records for one product.
    """
    prefix = (supplier.sku_value or '') if supplier.sku_type == 'prefix' else ''
    suffix = (supplier.sku_value or '') if supplier.sku_type == 'suffix' else ''
    return f'{prefix}{article}{suffix}'


def _pim_product_payload(name: str, description: str | None, number: str | None) -> dict:
    return {'name': name, 'description': description or '', 'number': number or ''}


def _push_pim_products(objects: list, payload_fn, batch_size: int = 1000, delay: float = 0.5) -> int:
    """Bulk-create `objects` as PriceManagerProduct records in PIM via
    upsertAsync, persisting the ids PIM returns onto obj.pim_id.

    Split into chunks of `batch_size` so a large `objects` list doesn't go out
    as one oversized upsertAsync payload/job, with `delay` seconds between
    consecutive chunks so batches are spaced out rather than fired back to
    back. `objects` must all be instances of the same model (bulk_update is
    called per chunk, on type(chunk[0])). A chunk whose transport/timeout/job
    call errors is skipped (recorded via _record_pim_error) without aborting
    the remaining chunks — a PIM outage must not fail the caller's larger
    task. Returns how many objects were successfully linked in total.
    """
    if not objects:
        return 0
    total_linked = 0
    chunk_starts = list(range(0, len(objects), batch_size))
    for i, start in enumerate(chunk_starts):
        if i > 0:
            time.sleep(delay)
        chunk = objects[start:start + batch_size]
        items = [{'entity': PIM_PRODUCT_ENTITY, 'payload': payload_fn(obj)} for obj in chunk]
        t0 = time.monotonic()
        try:
            results = upsert_async(items)
        except Exception as exc:
            _record_pim_error('push_pim_products', exc, int((time.monotonic() - t0) * 1000))
            continue
        if not isinstance(results, list) or not all(isinstance(r, dict) for r in results):
            _record_pim_error(
                'push_pim_products',
                Exception(f'unexpected upsertAsync result shape: {results!r:.500}'),
                int((time.monotonic() - t0) * 1000),
            )
            continue
        if len(results) != len(chunk):
            _record_pim_error(
                'push_pim_products',
                Exception(f'result count {len(results)} != item count {len(chunk)}'),
                int((time.monotonic() - t0) * 1000),
            )
            continue

        updated = []
        for obj, result in zip(chunk, results):
            if result.get('status') == 'Failed':
                continue
            pim_id = result.get('id')
            if pim_id:
                obj.pim_id = pim_id
                updated.append(obj)
        if updated:
            type(updated[0]).objects.bulk_update(updated, fields=['pim_id'])
        total_linked += len(updated)
    return total_linked


def push_supplier_products_to_pim(supplier_products, batch_size: int = 1000, delay: float = 0.5) -> int:
    """Bulk-create SupplierProduct rows lacking a pim_id as PriceManagerProduct
    records in PIM.

    `supplier_products` may be an iterable of SupplierProduct instances or
    pks (e.g. the rows just written by load_setting's bulk_create). pim_id is
    always re-read from the DB rather than trusted off the caller's in-memory
    instances, since bulk_create(update_conflicts=True) does not refresh
    non-pk fields on rows it updates rather than inserts — trusting the
    in-memory value would re-push every already-linked row on each re-import.
    """
    pks = [sp.pk if isinstance(sp, SupplierProduct) else sp for sp in supplier_products]
    targets = list(SupplierProduct.objects.filter(pk__in=pks, pim_id__isnull=True).select_related('supplier'))
    return _push_pim_products(
        targets,
        lambda sp: _pim_product_payload(sp.name, sp.description, compute_supplier_sku(sp.article, sp.supplier)),
        batch_size=batch_size,
        delay=delay,
    )


def push_missing_pim_products(products, batch_size: int = 1000, delay: float = 0.5) -> int:
    """Bulk-create MainProducts with no PIM match as PriceManagerProduct records.

    Callers must pass only products already confirmed absent from PIM
    (pim_id is None and _search_pim_id just found nothing) — this doesn't
    re-check, so a transient search miss on an already-linked product won't
    silently create a duplicate PIM record for it.
    """
    return _push_pim_products(
        list(products),
        lambda mp: _pim_product_payload(mp.name, mp.description, mp.sku),
        batch_size=batch_size,
        delay=delay,
    )


def create_pim_links(delay: float = 0.5, batch_size: int = 1000) -> tuple[int, int]:
    products = list(MainProduct.objects.filter(pim_id__isnull=True)[:1000])
    result = []
    missing = []
    created = 0
    for product in products:
        pim_id = _search_pim_id(product)
        if pim_id:
            product.pim_id = pim_id
            result.append(product)
        else:
            missing.append(product)
            if len(missing) >= batch_size:
                created += push_missing_pim_products(missing, batch_size=batch_size, delay=delay)
                missing = []
        time.sleep(delay)
    # bulk_update is the only DB write; kept outside the API loop so
    # execute_locked_task's transaction.atomic() doesn't span HTTP calls.
    if result:
        MainProduct.objects.bulk_update(result, fields=['pim_id'])
    created += push_missing_pim_products(missing, batch_size=batch_size, delay=delay)
    return len(result), created


def reindex_pim_ids(delay: float = 0.5, batch_size: int = 1000) -> tuple[int, int]:
    """Re-resolve pim_id for ALL MainProducts, including ones already linked.

    Unlike create_pim_links (which only fills pim_id__isnull=True), this
    re-searches PIM for every product so relinked/re-merged records pick up
    their new pim_id. Only writes products whose resolved pim_id changed.
    Products that were never linked and still aren't found get pushed to PIM
    (push_missing_pim_products) in batches of `batch_size` as soon as each
    batch fills up during the scan — not accumulated and sent only once the
    full (potentially very long) catalog scan finishes. `batch_size` does not
    limit how many MainProducts get processed here, every product is checked
    every run.
    """
    products = list(MainProduct.objects.all().order_by('pk'))
    result = []
    missing = []
    created = 0
    for product in products:
        if len(result) > batch_size:
            MainProduct.objects.bulk_update(result, fields=['pim_id'])
            result = []
        pim_id = _search_pim_id(product)
        if pim_id:
            if pim_id != product.pim_id:
                product.pim_id = pim_id
                result.append(product)
        elif product.pim_id is None:
            missing.append(product)
            if len(missing) >= batch_size:
                created += push_missing_pim_products(missing, batch_size=batch_size, delay=delay)
                missing = []
        time.sleep(delay)
    # bulk_update is the only DB write; kept outside the API loop so
    # execute_locked_task's transaction.atomic() doesn't span HTTP calls.
    if len(result) > 0:
        MainProduct.objects.bulk_update(result, fields=['pim_id'])
    created += push_missing_pim_products(missing, batch_size=batch_size, delay=delay)
    return len(result), created


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