import logging
import time

import httpx
from django.db.models import Max, F
from django.core.cache import cache
from django.db.models import Value, OuterRef, Subquery, Q, F, Sum, IntegerField
from django.utils import timezone
from django.contrib.postgres.search import SearchVectorField, SearchVector
from django.db.models.functions import Coalesce
from django.conf import settings

from pim_api import EntityList, Entity, Where, FileRecord, upsert_async as _upsert_async

from .models import MainProduct, MainProductLog, MP_PRICES
from .pim_client import site
from .columns import AVAILABLE_COLUMN_MAP, DEFAULT_VISIBLE_COLUMNS

from supplier_product_manager.models import SupplierProduct
from supplier_manager.models import Category, Manufacturer
from core.task_runner import dispatch_after_commit

logger = logging.getLogger(__name__)

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
    """GET a PIM `Product` by id straight from the API (no cache).

    pim_id is a PIM `Product` id — either one already stored on the MainProduct,
    or one _search_pim_id_result found by matching sku against `Product.number`.
    It is not a `ContributorProduct` id, which is why a single pim_id
    legitimately spans several MainProducts (see sync_pim_relations).

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
    """Enqueue the background relation-sync task for a pim_id we just fetched from PIM.

    Deduped via a short-lived cache flag (cache.add is atomic) so a burst of fetches
    for the same pim_id — e.g. rendering a product list — only fires one task.

    Dispatched via dispatch_after_commit because a caller may still be inside
    execute_locked_task's transaction: recalculate_vectors_missing_task reaches
    here through _build_searchvector -> _resolve_pim_id, which writes the new
    pim_id in that same transaction. sync_pim_relations looks products up by
    pim_id, so a task queued before the commit would find none and silently
    populate nothing.
    """
    queued_key = f"pim_populate_queued:{pim_id}"
    # Flag set before the deferred dispatch on purpose: if the transaction rolls
    # back, the pim_id write rolls back with it, so there is nothing left to
    # populate and suppressing the retry for the TTL is the right outcome.
    if not cache.add(queued_key, True, _PIM_POPULATE_QUEUED_TTL):
        return
    from .tasks import populate_pim_relations_task  # local: tasks imports this module
    dispatch_after_commit(populate_pim_relations_task, pim_id)


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
    data, not_found = _fetch_pim_product(pim_id)
    if data is not None:
        cache.set(cache_key, data, PIM_CACHE_TTL)
        _note_pim_success(pim_id)
        # Queue on every successful fetch, refresh=True included: whoever warms
        # this key owns the trigger, because it lasts PIM_CACHE_TTL and every
        # other caller only queues on a miss. Queueing from the miss branch
        # instead meant a refreshing caller — the detail views — suppressed
        # population, here and in prefetch_pim_data, for the next 24 hours.
        # After cache.set, so the task's own get_pim_data is a cache hit rather
        # than a second live fetch inside its transaction.
        _queue_pim_population(pim_id)
        return data
    if not_found:
        cache.delete(cache_key)
        _note_pim_404(pim_id)
        return None
    return cache.get(cache_key)


_PIM_NO_MATCH_TTL = 60 * 60 * 4  # 4 hours — avoid hammering PIM for unlinked products
_PIM_SEARCH_ERROR_TTL = 60 * 5  # 5 minutes — backoff after a search PIM never answered
_PIM_POPULATE_QUEUED_TTL = 60 * 10  # throttle for the post-fetch population trigger

# Outcomes of one _search_pim_id_result() call. The middle three double as the
# values cached under pim_no_match:{pk}, so the cached shortcut still tells the
# caller *why* the previous search came back empty.
_SEARCH_FOUND = "found"
_SEARCH_ABSENT = "absent"
_SEARCH_AMBIGUOUS = "ambiguous"
_SEARCH_ERROR = "error"
_SEARCH_NO_SKU = "no_sku"


class PimSearchError(RuntimeError):
    """A catalog scan ended with PIM searches that never got an answer."""


def _search_pim_id_result(product) -> tuple[str | None, str]:
    """Resolve a MainProduct's pim_id in PIM — returns (pim_id, outcome).

    The search is one `like` on the PIM `Product` attribute `number`, matched
    against `product.sku`. `outcome` is one of the _SEARCH_* constants, and
    callers must not collapse it back to "found or not": only _SEARCH_ABSENT
    means PIM was reached and answered that it holds no such product. The other
    three misses all mean "unknown", and treating one of them as an absence is
    what makes push_missing_pim_products create a second PIM record for a
    product that may already be in there:

    - _SEARCH_ERROR — the request failed, so nothing was learned.
    - _SEARCH_AMBIGUOUS — `like` matched several products, so no single one is
      *the* match. Returning the first (as this used to) links the product to
      whichever one PIM happened to list first.
    - _SEARCH_NO_SKU — no sku to search by, so PIM is never asked. Where.get()
      drops the value key when it is None (pim_api/__init__.py:24-25), so the
      request would otherwise go out as an unconstrained `like` on `number`.

    Misses are throttled through one cache key, pim_no_match:{pk}, holding the
    outcome that wrote it: a confirmed absence and an ambiguous match are
    conditions of the data and hold for _PIM_NO_MATCH_TTL, while an error holds
    only for _PIM_SEARCH_ERROR_TTL — a PIM outage costs minutes of suppressed
    retries, not hours. Does not persist the id — callers decide how/when to
    save it.
    """
    cache_key = f"pim_no_match:{product.pk}"
    cached = cache.get(cache_key)
    if isinstance(cached, str):
        return None, cached
    if cached is not None:
        # A bare True written by an older revision: it recorded no outcome, so
        # drop it and search again rather than guess which one it meant.
        cache.delete(cache_key)

    if not product.sku:
        return None, _SEARCH_NO_SKU

    t0 = time.monotonic()
    try:
        result = site.get(
            EntityList(
                name='Product',
                select=['id'],
                where=[Where(attribute='number', type='like', value=product.sku)],
            )
        )
    except Exception as exc:
        _record_pim_error("_search_pim_id", exc, int((time.monotonic() - t0) * 1000))
        cache.set(cache_key, _SEARCH_ERROR, _PIM_SEARCH_ERROR_TTL)
        return None, _SEARCH_ERROR

    pim_ids = [item.get('id') for item in result.get('list', []) if item.get('id')]
    if len(pim_ids) == 1:
        return pim_ids[0], _SEARCH_FOUND
    if pim_ids:
        logger.warning(
            "PIM number=%s matched %s products (MainProduct pk=%s) — linking none",
            product.sku, len(pim_ids), product.pk,
        )
        cache.set(cache_key, _SEARCH_AMBIGUOUS, _PIM_NO_MATCH_TTL)
        return None, _SEARCH_AMBIGUOUS

    cache.set(cache_key, _SEARCH_ABSENT, _PIM_NO_MATCH_TTL)
    return None, _SEARCH_ABSENT


def _search_pim_id(product) -> str | None:
    """The resolved id alone, for callers with nothing to decide on a miss.

    Anything that *writes* on a miss must call _search_pim_id_result and check
    the outcome instead — see push_missing_pim_products.
    """
    return _search_pim_id_result(product)[0]


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
    refresh_from_db — and it's re-resolved by sku before retrying once. The
    no-match cache is dropped first; without that, the cached outcome would
    short-circuit the re-resolve. This is the only place that clears it.
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


_PIM_FILE_URL_KEYS = ('url', 'downloadUrl')  # fallbacks, tried after {size}ThumbnailUrl


def _absolute_pim_url(value) -> str | None:
    """Turn one PIM File URL field into an absolute URL, or None if unusable.

    Sampled against the live PIM (both the File list and the single-record
    endpoint): only `downloadUrl` is ever present, always scheme-less
    `host/path` — so `https://` is what actually gets prepended today, and
    the `*ThumbnailUrl`/`url` branches are for a PIM that starts sending
    them. Deciding the scheme per value rather than prepending it
    unconditionally costs nothing and keeps that future from producing
    "https://https://...". A root-relative path has no host to build on, so
    it counts as unusable and lets the caller fall through to the next key
    instead of emitting "https:///upload/...".
    """
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    if value.startswith(('http://', 'https://')):
        return value
    if value.startswith('//'):
        return f'https:{value}'
    if value.startswith('/'):
        return None
    return f'https://{value}'


def get_file_url(file_id: str | None, size: str = 'medium') -> str | None:
    """Return an image URL for a PIM File record, or None if it has no usable one.

    Tries `{size}ThumbnailUrl`, then `url`, then `downloadUrl` — in practice
    only the last is populated. size: 'small', 'medium', 'large'.
    """
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
    # isinstance, not `data is None`: site.get returns whatever PIM's body
    # parses to, and a falsy non-None body (200 with `[]`) gets cached above,
    # so every later call skips the refetch and lands here with a non-dict.
    if not isinstance(data, dict):
        return None
    for key in (f'{size}ThumbnailUrl', *_PIM_FILE_URL_KEYS):
        url = _absolute_pim_url(data.get(key))
        if url:
            return url
    return None


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

def recalculate_search_vectors(mps):
    if not mps: return None
    mps = mps.select_related('supplier', 'manufacturer')
    def build_searchvector(mp):
      mp.search_vector = mp._build_searchvector()
      return mp
    mps = map(build_searchvector, mps)
    return MainProduct.objects.bulk_update(mps, fields=['search_vector'])


def update_stocks(logs: bool = True, batch_size: int = 10000) -> int:
    """Sync MainProduct.stock from each product's most recently updated SupplierProduct.

    A supplier row with no stock figure means "unknown", and an unknown stock
    is not sellable, so new_stock coalesces it to 0. MainProduct.stock is
    nullable for a different reason: NULL there means "never synced", which is
    distinct from a synced 0. That is why the candidate filter tests
    stock__isnull separately instead of coalescing the current value too —
    coalescing both sides made NULL -> 0 compare equal, so those products were
    never updated and never logged. The isnull branch stops matching after the
    first run, since the row is left with a non-NULL stock.

    Walks the catalog in `batch_size` chunks of a pk snapshot taken up front,
    so the MainProductLog list and its INSERT stay bounded instead of growing
    with the number of changed products. The chunk bounds come from real pks
    rather than offsets over count(), because a single gap in the id sequence
    would make an offset-derived range stop short and silently skip the tail
    of the catalog. Products created after the snapshot are picked up by the
    next run. Every batch stamps the same stock_updated_at, so one run still
    means one timestamp.
    """
    updated = 0
    now = timezone.now()
    stock_subq = (
        SupplierProduct.objects
        .filter(main_product_id=OuterRef('pk'))
        .order_by('-updated_at')
        .values('stock')[:1]
    )
    pks = list(MainProduct.objects.order_by('pk').values_list('pk', flat=True))
    for i in range(0, len(pks), batch_size):
        chunk = pks[i:i + batch_size]
        # chunk is a slice of every pk in pk order, so every existing product
        # between its ends is inside it — the range bounds select exactly
        # pk__in=chunk without shipping a batch_size-long IN list.
        mps = MainProduct.objects.filter(pk__gte=chunk[0], pk__lte=chunk[-1]).annotate(
            new_stock=Coalesce(Subquery(stock_subq, output_field=IntegerField()), Value(0), output_field=IntegerField()),
        ).filter(Q(stock__isnull=True) | ~Q(stock=F('new_stock')))
        if logs:
            mpls = [MainProductLog(main_product=mp, stock=mp.new_stock) for mp in mps]
            MainProductLog.objects.bulk_create(mpls, batch_size=batch_size)
        updated += mps.update(stock=F('new_stock'), stock_updated_at=now)
    return updated

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
            results = _upsert_async(site, items)
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
    targets = list(SupplierProduct.objects.filter(pk__in=pks, pim_id__isnull=True).select_related('supplier', 'main_product'))
    return _push_pim_products(
        targets,
        lambda sp: _pim_product_payload(
            sp.name,
            sp.description,
            (sp.main_product.sku if sp.main_product else None) or compute_supplier_sku(sp.article, sp.supplier),
        ),
        batch_size=batch_size,
        delay=delay,
    )


def push_missing_pim_products(products, batch_size: int = 1000, delay: float = 0.5) -> int:
    """Bulk-create MainProducts with no PIM match as PriceManagerProduct records.

    Callers must pass only products already confirmed absent from PIM —
    pim_id is None and _search_pim_id_result just came back _SEARCH_ABSENT.
    This doesn't re-check, so every other empty outcome (a failed request, an
    ambiguous `like`, a product with no sku to search by) must be filtered out
    by the caller: PIM cannot confirm an absence it was never asked about, and
    pushing on one creates a duplicate record for a product already in there.
    """
    return _push_pim_products(
        list(products),
        lambda mp: _pim_product_payload(mp.name, mp.description, mp.sku),
        batch_size=batch_size,
        delay=delay,
    )


def create_pim_links(delay: float = 0.5, batch_size: int = 1000) -> tuple[int, int]:
    # The window is the first 1000 unlinked products in pk order (Meta.ordering
    # = ['id']), so it is the same rows every run until they leave the unlinked
    # set. A product with no sku never can: _search_pim_id_result returns
    # _SEARCH_NO_SKU without asking PIM, and it must not be pushed either
    # (_pim_product_payload would create a PIM record with number=''). Excluded
    # here so it doesn't hold a slot — and a delay — against products the scan
    # can still resolve. Drop the exclusion if a search that works without an
    # sku is ever added back.
    products = list(
        MainProduct.objects
        .filter(pim_id__isnull=True)
        .exclude(sku__isnull=True)
        .exclude(sku='')[:1000]
    )
    result = []
    missing = []
    created = 0
    unanswered = 0
    for product in products:
        pim_id, outcome = _search_pim_id_result(product)
        if pim_id:
            product.pim_id = pim_id
            result.append(product)
        elif outcome == _SEARCH_ABSENT:
            # Only a confirmed absence may be pushed as a new PIM record; an
            # error or an ambiguous match leaves the product for a later run.
            missing.append(product)
            if len(missing) >= batch_size:
                created += push_missing_pim_products(missing, batch_size=batch_size, delay=delay)
                missing = []
        elif outcome == _SEARCH_ERROR:
            unanswered += 1
        time.sleep(delay)
    # Runs with no transaction held (create_pim_links_task passes atomic=False),
    # so each write below commits on its own rather than idling a transaction
    # open across the PIM calls above. Safe to resume after a partial run: this
    # only ever fills pim_id__isnull=True, so committed rows are simply skipped
    # next time, and a row skipped over a PIM error is retried once its
    # _PIM_SEARCH_ERROR_TTL backoff expires.
    if result:
        MainProduct.objects.bulk_update(result, fields=['pim_id'])
    created += push_missing_pim_products(missing, batch_size=batch_size, delay=delay)
    if unanswered:
        # Raised after the writes, so the progress above stays committed. The
        # run is recorded as an error instead of a success over a dead PIM:
        # TaskRunHistory is the only durable signal, maybe_notify_pim_error
        # being DEBUG-gated and prod running under settings.prod.
        raise PimSearchError(
            f'PIM не ответил на поиск по {unanswered} из {len(products)} товаров: '
            f'связано {len(result)}, создано в PIM {created}'
        )
    return len(result), created


def iter_pim_id_pk_batches(batch_size: int = 1000, skip_non_empty: bool = False):
    """Yield MainProduct pks in pk order, chunked to `batch_size` each.

    Used by reindex_pim_ids_task to fan out one reindex_pim_ids_batch_task
    per chunk, so the full catalog re-scan runs as separate parallel Celery
    tasks instead of a single long sequential loop. With skip_non_empty,
    products that already have a pim_id are excluded, so the re-scan only
    resolves products still missing one.
    """
    products = MainProduct.objects.order_by('pk')
    if skip_non_empty:
        products = products.filter(pim_id__isnull=True)
    pks = list(products.values_list('pk', flat=True))
    for i in range(0, len(pks), batch_size):
        yield pks[i:i + batch_size]


def reindex_pim_ids_batch(pks: list[int], delay: float = 0.5, batch_size: int = 1000) -> tuple[int, int]:
    """Re-resolve pim_id for one batch of MainProducts, including ones already linked.

    Unlike create_pim_links (which only fills pim_id__isnull=True), this
    re-searches PIM for every product in the batch so relinked/re-merged
    records pick up their new pim_id. Only writes products whose resolved
    pim_id changed. Products that were never linked and still aren't found
    get pushed to PIM via push_missing_pim_products.

    Runs as its own Celery task (see reindex_pim_ids_batch_task) — pks is one
    chunk produced by iter_pim_id_pk_batches, so many batches process in
    parallel across Celery workers instead of one product at a time.
    """
    products = MainProduct.objects.filter(pk__in=pks).order_by('pk')
    result = []
    missing = []
    unanswered = 0
    for product in products:
        pim_id, outcome = _search_pim_id_result(product)
        if pim_id:
            if pim_id != product.pim_id:
                product.pim_id = pim_id
                result.append(product)
        elif outcome == _SEARCH_ABSENT and product.pim_id is None:
            # As in create_pim_links: only a confirmed absence gets pushed.
            missing.append(product)
        elif outcome == _SEARCH_ERROR:
            unanswered += 1
        time.sleep(delay)
    # Runs with no transaction held (reindex_pim_ids_batch_task passes
    # atomic=False), so each write below commits on its own rather than idling
    # a transaction open across the PIM calls above. Safe to resume after a
    # partial run: re-searching is idempotent, only a changed pim_id is written
    # back, and a row skipped over a PIM error is retried once its
    # _PIM_SEARCH_ERROR_TTL backoff expires.
    if result:
        MainProduct.objects.bulk_update(result, fields=['pim_id'])
    created = push_missing_pim_products(missing, batch_size=batch_size, delay=delay)
    if unanswered:
        # See create_pim_links: raised after the writes so committed progress
        # survives, and the batch is recorded as an error, not a success.
        raise PimSearchError(
            f'PIM не ответил на поиск по {unanswered} из {len(pks)} товаров партии: '
            f'связано {len(result)}, создано в PIM {created}'
        )
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


def delete_outdated_logs(keep: int = 100_000) -> int:
    """Trim the log table down to its newest `keep` rows, returning how many went.

    The order_by is explicit on purpose. MainProductLog.Meta.ordering is
    ['-update_time'], so a bare `.all()[keep:]` would happen to work here —
    but relying on Meta.ordering is what produced the original bug, where
    `.all()[:keep]` resolved to ORDER BY update_time DESC LIMIT keep and
    deleted the newest rows while keeping the oldest.

    '-id' is a tiebreaker, not decoration: update_logs and PriceManager.apply
    bulk_create whole batches at one wall-clock instant, so update_time ties
    are routine and Meta.ordering has no secondary key. Without it the cut
    between kept and deleted rows falls arbitrarily inside a tied batch.
    """
    if MainProductLog.objects.count() > keep:
        outdated = MainProductLog.objects.order_by('-update_time', '-id')[keep:]
        return MainProductLog.objects.filter(
            id__in=outdated.values_list('id', flat=True)
        ).delete()[0]
    return 0
