import logging
import re
import time
from urllib.parse import urljoin, urlsplit

import httpx
from django.conf import settings
from django.db.models import Max, F
from django.core.cache import cache
from django.db.models import Value, OuterRef, Subquery, Q, F, Sum, IntegerField, Count, Min
from django.utils import timezone
from django.contrib.postgres.search import SearchVectorField, SearchVector
from django.db.models.functions import Coalesce, Length

from pim_api import EntityList, Entity, Where, FileRecord, upsert_async as _upsert_async

from .models import MainProduct, MainProductLog, MP_PRICES
from product.models import Product as PimProduct
from .pim_client import site
from .columns import AVAILABLE_COLUMN_MAP, DEFAULT_VISIBLE_COLUMNS

from supplier_product_manager.models import SupplierProduct
from supplier_manager.models import Category, Manufacturer
from core.task_runner import dispatch_after_commit

logger = logging.getLogger(__name__)

PRODUCT_NUMBER_MAX_LENGTH = PimProduct._meta.get_field('number').max_length
PRODUCT_NAME_MAX_LENGTH = PimProduct._meta.get_field('name').max_length


def _pim_id_of(product) -> str | None:
    """PIM `PriceManagerProduct` id of a MainProduct's local Product, or None.

    The link runs MainProduct -> product.Product (local, matched by
    number = sku) -> product.Product.pim_id, the id of the PriceManagerProduct
    record reindex pushed for that Product. The PIM `Product` itself is one
    more hop, on the PMP's productId — see get_pim_data.

    Deliberately a function and not a MainProduct property: a property named
    pim_id would keep working in templates and silently break in
    .filter()/annotations, where the lookup has to be `product__pim_id`.

    Callers iterating a queryset must select_related('product') — otherwise this
    is one query per row.
    """
    return product.product.pim_id if product.product_id else None


def _link_to_local_product(product) -> bool:
    """Link an unlinked MainProduct to the existing local Product with number = sku.

    The render-path counterpart of link_unlinked_main_products: it never
    creates a Product and never talks to PIM — creating and pushing is left to
    reindex. Returns whether the product is linked afterwards.
    """
    if product.product_id:
        return True
    if not product.sku:
        return False
    row = PimProduct.objects.filter(number=product.sku).first()
    if row is None:
        return False
    MainProduct.objects.filter(pk=product.pk, product__isnull=True).update(product=row)
    product.product = row
    return True

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
    """Create one throttled PersistentNotification per error window when PIM is failing.

    Deliberately *not* gated on settings.DEBUG. It used to be, which inverted the
    intent: DEBUG defaults to false (settings/base.py), so the one environment
    where a PIM outage actually costs something — production — was the one
    environment that got no signal at all. Errors landed in the `pim_last_error`
    cache key and nothing ever read it.

    What keeps this from spamming is the per-user throttle below
    (_PIM_NOTIF_THROTTLE_TTL), not the environment.
    """
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


PIM_LINK_ENTITY = 'PriceManagerProduct'


def _fetch_pim_entity(name: str, entity_id: str) -> tuple[dict | None, bool]:
    """GET one PIM record by entity name and id straight from the API (no cache).

    Returns (data, not_found) — not_found is True only on an explicit 404,
    so callers can tell "PIM deleted this id" apart from a transient
    network/API error.
    """
    t0 = time.monotonic()
    try:
        data = site.get(Entity(name=name, id=entity_id))
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
    here through _build_searchvector -> _link_to_local_product, which writes
    the MainProduct link in that same transaction. sync_pim_relations looks
    products up through that link, so a task queued before the commit would
    find none and silently populate nothing.
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
    """Track a 404 on a PriceManagerProduct; once _PIM_404_THRESHOLD is hit in
    a row, clear product.Product.pim_id so renders stop hammering a dead id.

    Only the PIM-side link is dropped: MainProducts stay linked to their local
    Product (that link is local, by sku), and the next reindex pushes a new
    PriceManagerProduct for it. A 404 on the PIM Product the PMP points at
    never reaches here — that is PIM's link to fix, not ours.
    """
    count_key = f"{_PIM_404_COUNT_PREFIX}{pim_id}"
    count = cache.get(count_key, 0) + 1
    if count < _PIM_404_THRESHOLD:
        cache.set(count_key, count, _PIM_404_COUNT_TTL)
        return
    cache.delete(count_key)
    PimProduct.objects.filter(pim_id=pim_id).update(pim_id=None)


def _note_pim_success(pim_id: str) -> None:
    cache.delete(f"{_PIM_404_COUNT_PREFIX}{pim_id}")


def _get_pim_link(pim_id: str, refresh: bool = False) -> dict | None:
    """The PriceManagerProduct record for a local Product's pim_id, cached."""
    cache_key = f"pim_link:{pim_id}"
    if not refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
    data, not_found = _fetch_pim_entity(PIM_LINK_ENTITY, pim_id)
    if data is not None:
        cache.set(cache_key, data, PIM_CACHE_TTL)
        _note_pim_success(pim_id)
        return data
    if not_found:
        cache.delete(cache_key)
        _note_pim_404(pim_id)
        return None
    return cache.get(cache_key)


def get_pim_data(pim_id: str | None, refresh: bool = False) -> dict | None:
    """PIM `Product` data for a local Product's pim_id (a PriceManagerProduct id).

    Two hops: PriceManagerProduct/{pim_id} for its productId, then
    Product/{productId}. None while the PMP is not linked to a PIM Product yet
    — PIM staff set that link, or reindex did when the number search found one.

    The two hops cache under different keys on purpose: the Product fetch is
    keyed by productId, not by pim_id, so several local Products whose PMPs
    point at one PIM Product still share a single Product round-trip.
    """
    if not pim_id:
        return None
    link = _get_pim_link(pim_id, refresh=refresh)
    if not isinstance(link, dict):
        return None
    product_id = link.get('productId')
    if not product_id:
        return None
    cache_key = f"pim_product:{product_id}"
    if not refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
    data, not_found = _fetch_pim_entity('Product', product_id)
    if data is not None:
        cache.set(cache_key, data, PIM_CACHE_TTL)
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
        return None
    return cache.get(cache_key)


_PIM_POPULATE_QUEUED_TTL = 60 * 10  # throttle for the post-fetch population trigger

# Outcomes of one _search_pim_product_id() call.
_SEARCH_FOUND = "found"
_SEARCH_ABSENT = "absent"
_SEARCH_AMBIGUOUS = "ambiguous"
_SEARCH_ERROR = "error"


class PimScanError(RuntimeError):
    """A reindex batch ended with PIM searches unanswered or pushes rejected."""


def _search_pim_product_id(number: str) -> tuple[str | None, str]:
    """Find the PIM `Product` whose number equals `number` — returns (id, outcome).

    Only reindex calls this, to fill a new PriceManagerProduct's productId; the
    render path never searches PIM. `number` must be non-empty: Where.get()
    drops the value key when it is None (pim_api/__init__.py:24-25), so the
    request would otherwise go out as an unconstrained match.

    The search must stay `equals`, not `like`: AtroPIM passes a `like` value
    straight into SQL LIKE, so `_` matches any single character and `%`
    matches anything. Verified against the live API — `like '2001_-04_z01'`
    returns the product numbered `20015-04_z01` — and PIM numbers routinely
    contain `_` while sku is supplier-supplied.

    `outcome` is one of the _SEARCH_* constants. Callers must keep
    _SEARCH_ERROR apart from the rest: an error learned nothing, so pushing
    then would create the PMP without a productId the search could have found.
    PIM's metadata does not declare Product.number unique, so several matches
    come back as _SEARCH_AMBIGUOUS and link none of them.
    """
    t0 = time.monotonic()
    try:
        result = site.get(
            EntityList(
                name='Product',
                select=['id'],
                where=[Where(attribute='number', type='equals', value=number)],
            )
        )
    except Exception as exc:
        _record_pim_error("_search_pim_product_id", exc, int((time.monotonic() - t0) * 1000))
        return None, _SEARCH_ERROR

    pim_ids = [item.get('id') for item in result.get('list', []) if item.get('id')]
    if len(pim_ids) == 1:
        return pim_ids[0], _SEARCH_FOUND
    if pim_ids:
        logger.warning(
            "PIM Product number=%s matched %s products — PriceManagerProduct goes out without productId",
            number, len(pim_ids),
        )
        return None, _SEARCH_AMBIGUOUS
    return None, _SEARCH_ABSENT


def get_pim_data_for_product(product, refresh: bool = False) -> dict | None:
    """Return PIM data for a MainProduct, linking it to a local Product first if one matches its sku.

    Never creates a Product or pushes to PIM — an unlinked product, or one
    whose Product has no pim_id yet, simply has no PIM data until reindex runs.
    """
    if not product.product_id:
        _link_to_local_product(product)
    return get_pim_data(_pim_id_of(product), refresh=refresh)


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
    """Sync manufacturer + categories for every MainProduct under this pim_id.

    pim_id is a PriceManagerProduct id, so it names one local Product, and
    several MainProducts (from different suppliers) share that Product through
    a common sku — this updates all of them in one go. `data` is the PIM
    `Product` the PMP points at (get_pim_data).
    """
    products = list(MainProduct.objects.filter(product__pim_id=pim_id))
    if not products:
        return 0

    manufacturer = _resolve_manufacturer(data)
    if manufacturer:
        MainProduct.objects.filter(product__pim_id=pim_id).update(manufacturer=manufacturer)

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

    Table rendering never links products or pushes to PIM — that's the job of
    reindex_pim_ids. A product without a pim_id, or whose pim_id 404s with
    nothing cached, is simply skipped here rather than triggering a live PIM
    search.
    """
    result = {}
    for product in products:
        pim_id = _pim_id_of(product)
        if not pim_id:
            continue
        data = get_pim_data(pim_id)
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
    """Return the PIM-side image URL for a PIM File record, or None if it has no usable one.

    Tries `{size}ThumbnailUrl`, then `url`, then `downloadUrl`. size: 'small',
    'medium', 'large'. As of 2026-09-21 the live PIM does send the thumbnail
    keys (earlier samples had only `downloadUrl`).

    The URL needs PIM's Authorization-Token — anonymously it is a 401. Never
    put it in a template; <img src> gets pim_image_url(), our proxy.
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


# --- Фото из PIM — через наш прокси ------------------------------------------
#
# get_file_url возвращает адрес НА СТОРОНЕ PIM, и отдавать его браузеру нельзя:
# и миниатюры, и оригиналы PIM отдаёт только с Authorization-Token, анонимный
# запрос получает 401 (проверено на живом PIM 2026-09-21). <img src> на PIM
# работал лишь у того, кто случайно залогинен в PIM в том же браузере, — у
# остальных фото «не отображалось». Поэтому браузер ходит к нам
# (product.views.PimImageView, за LoginRequiredMiddleware), а мы — в PIM с
# токеном.

PIM_IMAGE_SIZES = ('small', 'medium', 'large')
_PIM_FILE_ID = re.compile(r'[A-Za-z0-9-]{1,64}')
_PIM_IMAGE_MAX_BYTES = 5 * 1024 * 1024
_PIM_IMAGE_MAX_REDIRECTS = 3


def _on_pim_host(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == 'https' and (parts.hostname or '').lower() == str(settings.PIM_HOST).lower()


def _valid_pim_image(file_id, size) -> bool:
    return bool(file_id) and size in PIM_IMAGE_SIZES and bool(_PIM_FILE_ID.fullmatch(str(file_id)))


def pim_image_url(file_id: str | None, size: str = 'medium') -> str | None:
    """Адрес фото для <img src> — наш прокси, не PIM. Сети не касается."""
    if not _valid_pim_image(file_id, size):
        return None
    from django.urls import reverse
    return reverse('pim-image', kwargs={'file_id': file_id, 'size': size})


def fetch_pim_image(file_id: str | None, size: str = 'medium') -> tuple[bytes, str] | None:
    """Байты и content-type фото из PIM, либо None.

    Токен уходит ТОЛЬКО на хост из settings.PIM_HOST. Адрес картинки берётся
    из ответа PIM, и если PIM однажды укажет на внешнее хранилище, отправить
    туда наш токен значило бы его раздать. Такой адрес отвергается, а не
    запрашивается без токена: без токена PIM всё равно отвечает 401.

    Редиректы — вручную и с той же проверкой на каждом шаге. Они не
    исключение, а норма: миниатюра отвечает 302 на относительный
    /upload/thumbnails/… того же хоста (проверено на живом PIM). httpx с
    follow_redirects=True пошёл бы за ними сам — и понёс бы токен куда угодно,
    Authorization-Token он при смене хоста не снимает.

    Неудача не кэшируется: чаще всего она временная, а битая картинка на сутки
    хуже лишнего запроса.
    """
    if not _valid_pim_image(file_id, size):
        return None
    cache_key = f'pim_image:{file_id}:{size}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    url = get_file_url(file_id, size)
    t0 = time.monotonic()
    try:
        for _ in range(_PIM_IMAGE_MAX_REDIRECTS + 1):
            if not url or not _on_pim_host(url):
                return None
            response = httpx.get(url, headers={'Authorization-Token': settings.PIM_TOKEN},
                                 timeout=15, follow_redirects=False)
            if not response.is_redirect:
                break
            url = urljoin(url, response.headers.get('location', ''))
        else:
            return None
    except httpx.HTTPError as exc:
        _record_pim_error('fetch_pim_image', exc, int((time.monotonic() - t0) * 1000))
        return None
    content_type = response.headers.get('content-type', '').split(';')[0].strip()
    if (response.status_code != 200 or not content_type.startswith('image/')
            or len(response.content) > _PIM_IMAGE_MAX_BYTES):
        return None
    image = (response.content, content_type)
    cache.set(cache_key, image, PIM_CACHE_TTL)
    return image


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
    # 'product' обязателен: _build_searchvector зовёт _pim_id_of, а тот ходит
    # по FK. Без него каждый уже привязанный товар — лишний запрос; раньше
    # pim_id лежал в самой строке и доставался даром.
    mps = mps.select_related('supplier', 'manufacturer', 'product')
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

def compute_supplier_sku(article: str, supplier) -> str:
    """The MainProduct.sku a SupplierProduct.article turns into once copied to
    MainProduct (copy_supplier_products_to_main_task) — prefixed/suffixed per
    supplier.sku_type/sku_value. That sku is what reindex matches against
    product.Product.number, so change it here and every copied product lands
    on a different local Product — and a different PriceManagerProduct.
    """
    prefix = (supplier.sku_value or '') if supplier.sku_type == 'prefix' else ''
    suffix = (supplier.sku_value or '') if supplier.sku_type == 'suffix' else ''
    return f'{prefix}{article}{suffix}'


def backfill_product_numbers() -> int:
    """Give a number to local Products that have none, from their MainProducts' sku.

    Rows seeded by product.0005 / main_product_manager.0011 carry no number,
    so they can be neither searched nor pushed. Such a Product takes its
    MainProducts' sku when that is unambiguous: every linked MainProduct with
    a sku has the same one, it fits number's max_length, and no other Product
    holds that number yet. Anything else is logged and left alone — guessing
    would put two products under one PIM record, and existing links are not
    reindex's to move. Returns how many Products got a number.

    Runs before link_unlinked_main_products on purpose: a placeholder claims
    its sku first, so unlinked MainProducts with that sku join it instead of
    getting a second Product that would then block this backfill for good.
    """
    has_sku = ~Q(main_products__sku='')
    candidates = (
        PimProduct.objects.filter(number__isnull=True)
        .annotate(
            sku_count=Count('main_products__sku', distinct=True, filter=has_sku),
            first_sku=Min('main_products__sku', filter=has_sku),
        )
        .filter(sku_count__gte=1)
        .order_by('pk')
    )
    taken = set(PimProduct.objects.exclude(number__isnull=True).values_list('number', flat=True))
    numbered = []
    conflicts = 0
    for product in candidates.iterator():
        sku = product.first_sku
        if product.sku_count != 1 or len(sku) > PRODUCT_NUMBER_MAX_LENGTH or sku in taken:
            conflicts += 1
            continue
        product.number = sku
        taken.add(sku)
        numbered.append(product)
    if numbered:
        PimProduct.objects.bulk_update(numbered, fields=['number'], batch_size=1000)
    if conflicts:
        logger.warning(
            'backfill_product_numbers: %s Products left without a number '
            '(MainProducts disagree on sku, sku too long, or the number is taken)',
            conflicts,
        )
    return len(numbered)


def link_unlinked_main_products(batch_size: int = 1000) -> int:
    """Link every unlinked MainProduct that has a sku to the local Product with number = sku.

    A sku with no Product yet gets one (number = sku, name = the lowest-pk
    such MainProduct's name), so afterwards every linkable MainProduct is
    linked. Existing links are never touched: a MainProduct already on a
    Product keeps it even if its sku now says otherwise.

    Pure DB work, safe inside execute_locked_task's transaction. A sku longer
    than number's max_length can never be a number, so it stays unlinked and
    is counted in the log rather than failing the bulk_create. Returns how
    many MainProducts were linked.
    """
    def unlinked():
        return MainProduct.objects.filter(product__isnull=True).exclude(sku__isnull=True).exclude(sku='')

    before = unlinked().count()
    if not before:
        return 0
    with_length = unlinked().annotate(sku_length=Length('sku'))
    too_long = with_length.filter(sku_length__gt=PRODUCT_NUMBER_MAX_LENGTH).count()
    if too_long:
        logger.warning(
            'link_unlinked_main_products: %s MainProducts have a sku longer than %s chars — left unlinked',
            too_long, PRODUCT_NUMBER_MAX_LENGTH,
        )
    linkable = with_length.filter(sku_length__lte=PRODUCT_NUMBER_MAX_LENGTH)

    skus = list(linkable.order_by('sku').values_list('sku', flat=True).distinct())
    for start in range(0, len(skus), batch_size):
        chunk = skus[start:start + batch_size]
        existing = set(PimProduct.objects.filter(number__in=chunk).values_list('number', flat=True))
        missing = [sku for sku in chunk if sku not in existing]
        if not missing:
            continue
        names = {}
        for sku, name in linkable.filter(sku__in=missing).order_by('sku', 'pk').values_list('sku', 'name'):
            names.setdefault(sku, name)
        PimProduct.objects.bulk_create(
            [
                PimProduct(number=sku, name=(names.get(sku) or '')[:PRODUCT_NAME_MAX_LENGTH] or None)
                for sku in missing
            ],
            batch_size=batch_size,
            # number is unique: a row created since `existing` was read is
            # simply the Product this sku should link to.
            ignore_conflicts=True,
        )

    # One correlated UPDATE rather than one per sku. A sku with no Product
    # (only the too-long ones by now) gets NULL from the subquery, which is
    # what it already had — so count what got linked instead of trusting
    # update()'s row count.
    unlinked().update(
        product_id=Subquery(PimProduct.objects.filter(number=OuterRef('sku')).values('id')[:1])
    )
    return before - unlinked().count()


def iter_unpushed_product_pk_batches(batch_size: int = 1000):
    """Yield pks of local Products still waiting for a PriceManagerProduct, chunked.

    Waiting means pim_id NULL, a number to push under, and at least one
    MainProduct — the PMP takes its name and description from one, and a
    Product nothing links to has no business in PIM. Used by
    reindex_pim_ids_task to fan out one reindex_pim_ids_batch_task per chunk.
    """
    pks = list(
        PimProduct.objects
        .filter(pim_id__isnull=True, number__isnull=False, main_products__isnull=False)
        .order_by('pk')
        .values_list('pk', flat=True)
        .distinct()
    )
    for start in range(0, len(pks), batch_size):
        yield pks[start:start + batch_size]


def _take_over_pim_link(payload: dict) -> str | None:
    """Repoint the PriceManagerProduct holding payload's number at our Product.

    Reached when PIM rejected a push. PIM matches an upsert on the PMP's two
    unique fields, so a rejection means one of them sits on a record whose
    other one differs — typically our number on a PMP whose platformID is
    someone else's (a local Product deleted and recreated under a new pk, or
    another environment pushed first). Upserting that record by id with our
    payload rewrites its platformID — and name, description and, when the
    search found one, productId — to ours.

    Returns the PMP id, or None when no single PMP holds the number or PIM
    refuses the rewrite too (our platformID already on a PMP with another
    number).
    """
    t0 = time.monotonic()
    try:
        found = site.get(EntityList(
            name=PIM_LINK_ENTITY,
            select=['id', 'platformID'],
            where=[Where(attribute='number', type='equals', value=payload['number'])],
        ))
        records = [item for item in (found.get('list') or []) if item.get('id')] if isinstance(found, dict) else []
        if len(records) != 1:
            return None
        results = _upsert_async(site, [{'entity': PIM_LINK_ENTITY, 'payload': {**payload, 'id': records[0]['id']}}])
    except Exception as exc:
        _record_pim_error('take_over_pim_link', exc, int((time.monotonic() - t0) * 1000))
        return None
    if not (isinstance(results, list) and len(results) == 1 and isinstance(results[0], dict)):
        return None
    result = results[0]
    if result.get('status') == 'Failed' or not result.get('id'):
        return None
    logger.warning(
        'PriceManagerProduct %s (number=%s) repointed from platformID=%s to %s',
        result['id'], payload['number'], records[0].get('platformID'), payload['platformID'],
    )
    return result['id']


def _push_pim_links(targets: list, batch_size: int = 1000, delay: float = 0.5) -> tuple[int, int]:
    """upsertAsync `targets` — [(Product, payload), ...] — as PriceManagerProduct
    records and store each returned id as that Product's pim_id.

    Chunked to `batch_size` items per job, `delay` seconds between jobs. A
    chunk whose transport/timeout/job call errors, or whose result has the
    wrong shape or length, is recorded via _record_pim_error and skipped
    without aborting the rest: results are tied back to Products only by
    position, so a short or malformed list must never be zipped.

    PIM matches an upsert on number + platformID (verified live): both on one
    record answers NotModified/Updated with its id — how a PMP whose id was
    lost gets it back — while only one of them matching fails the item with a
    unique-violation 400 inside a job that still ends as Success. A rejected
    item goes to _take_over_pim_link; what even that cannot place is logged
    and recorded. Returns (linked, rejected).
    """
    total_linked = 0
    total_rejected = 0
    for i, start in enumerate(range(0, len(targets), batch_size)):
        if i > 0:
            time.sleep(delay)
        chunk = targets[start:start + batch_size]
        items = [{'entity': PIM_LINK_ENTITY, 'payload': payload} for _, payload in chunk]
        t0 = time.monotonic()
        try:
            results = _upsert_async(site, items)
        except Exception as exc:
            _record_pim_error('push_pim_links', exc, int((time.monotonic() - t0) * 1000))
            continue
        if not isinstance(results, list) or not all(isinstance(r, dict) for r in results):
            _record_pim_error(
                'push_pim_links',
                Exception(f'unexpected upsertAsync result shape: {results!r:.500}'),
                int((time.monotonic() - t0) * 1000),
            )
            continue
        if len(results) != len(chunk):
            _record_pim_error(
                'push_pim_links',
                Exception(f'result count {len(results)} != item count {len(chunk)}'),
                int((time.monotonic() - t0) * 1000),
            )
            continue

        linked = []
        rejected = []
        for (product, payload), result in zip(chunk, results):
            pim_id = result.get('id')
            if result.get('status') == 'Failed' or not pim_id:
                pim_id = _take_over_pim_link(payload)
                if not pim_id:
                    rejected.append(result)
                    continue
            product.pim_id = pim_id
            linked.append(product)
        if rejected:
            error = Exception(
                f'PIM отклонил {len(rejected)} из {len(chunk)} товаров; '
                f'первый ответ: {rejected[0]!r:.500}'
            )
            logger.error('push_pim_links: %s', error)
            _record_pim_error('push_pim_links', error, int((time.monotonic() - t0) * 1000))
        if linked:
            # A taken-over PMP may still be stored on the Product it used to
            # point at; that Product lost it in PIM, so it loses it here too
            # (and is pushed afresh next run) rather than tripping pim_id's
            # unique constraint.
            PimProduct.objects.filter(pim_id__in=[p.pim_id for p in linked]).exclude(
                pk__in=[p.pk for p in linked]
            ).update(pim_id=None)
            PimProduct.objects.bulk_update(linked, fields=['pim_id'])
        total_linked += len(linked)
        total_rejected += len(rejected)
    return total_linked, total_rejected


def push_pim_links(pks: list[int], delay: float = 0.5, batch_size: int = 1000) -> int:
    """Create the PriceManagerProduct for one batch of local Products and store its id as pim_id.

    For each Product still without a pim_id: search the PIM Product by
    number, then push {platformID: our pk, number, name, description} — plus
    productId when the search found exactly one. An ambiguous search pushes
    without productId, leaving PIM staff to pick the product; a failed search
    skips the Product, since pushing then would drop a productId the search
    might have found. The key is left out rather than sent as null when there
    is no match, so a push never clears a link PIM staff already set.

    Runs as reindex_pim_ids_batch_task with atomic=False, so the writes commit
    as they go instead of idling a transaction across the PIM calls. Safe to
    resume: a Product that got its pim_id drops out of the next run's batches,
    and a repeat push of a PMP whose id was never saved answers with that id.
    Raises PimScanError after its writes if any search went unanswered or any
    push stayed rejected, so the batch is recorded as an error, not a success.
    """
    products = list(
        PimProduct.objects.filter(pk__in=pks, pim_id__isnull=True, number__isnull=False).order_by('pk')
    )
    if not products:
        return 0
    first_main_product = {}
    for product_id, name, description in (
        MainProduct.objects.filter(product_id__in=[p.pk for p in products])
        .order_by('product_id', 'pk')
        .values_list('product_id', 'name', 'description')
    ):
        first_main_product.setdefault(product_id, (name, description))

    targets = []
    unanswered = 0
    for product in products:
        if product.pk not in first_main_product:
            continue
        pim_product_id, outcome = _search_pim_product_id(product.number)
        time.sleep(delay)
        if outcome == _SEARCH_ERROR:
            unanswered += 1
            continue
        name, description = first_main_product[product.pk]
        payload = {
            'platformID': str(product.pk),
            'number': product.number,
            'name': name or product.name or product.number,
            'description': description or '',
        }
        if pim_product_id:
            payload['productId'] = pim_product_id
        targets.append((product, payload))

    linked, rejected = _push_pim_links(targets, batch_size=batch_size, delay=delay)
    if unanswered or rejected:
        raise PimScanError(
            f'Партия из {len(products)} товаров: PIM не ответил на поиск по {unanswered}, '
            f'отклонил {rejected}; связано с PIM {linked}'
        )
    return linked


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
