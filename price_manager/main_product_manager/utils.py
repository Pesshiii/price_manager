import logging
import re
import time
from urllib.parse import urljoin, urlsplit

import httpx
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.db.models import Max, F
from django.core.cache import cache
from django.db.models import Value, OuterRef, Subquery, Exists, Q, F, Sum, IntegerField, Count, Min
from django.utils import timezone
from django.db.models.functions import Coalesce, Length, Lower

from pim_api import EntityList, Entity, Where, FileRecord, upsert_async as _upsert_async

from .models import MainProduct, MainProductLog, MP_PRICES
from product.models import Product as PimProduct
from .pim_client import site

from supplier_product_manager.models import SupplierProduct
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


def row_brand_subquery():
    """The brand of a MainProduct (OuterRef('pk')): its price-list row's brand.

    A ГП row has no brand of its own. Its price-list row (at most one:
    SupplierProduct.main_product is unique) has the supplier's brand column,
    resolved to a PIM brand (SupplierProduct.brand, product/services/brands.py),
    and when the supplier names no brand, the brand of the row's current
    Product (inherit_product_brands). A hand-made row has none.
    """
    return Subquery(
        SupplierProduct.objects.filter(main_product_id=OuterRef('pk'), brand__isnull=False)
        .values('brand_id')[:1]
    )


def row_brand_id(main_product) -> int | None:
    """row_brand_subquery for one row."""
    return (
        SupplierProduct.objects.filter(main_product_id=main_product.pk, brand__isnull=False)
        .values_list('brand_id', flat=True).first()
    )


def resolve_product(sku: str, brand_id: int | None = None, name: str | None = None):
    """The Product a ГП row with this sku and brand belongs to: found, else created.

    A product is the pair (number, brand), number compared case-insensitively
    (product_product_number_brand_uniq). With a brand it is found or created;
    a concurrent create of the same pair is the Product we wanted, hence the
    re-read on IntegrityError. Without a brand there is nothing to find by:
    brandless products sharing a number are different products until they get
    a brand, so every call creates a new one. DB only, no PIM — pushing is
    reindex's job.
    """
    from django.db import IntegrityError, transaction

    sku = sku.strip()
    name = (name or '')[:PRODUCT_NAME_MAX_LENGTH] or None
    if brand_id is None:
        return PimProduct.objects.create(number=sku, name=name)
    product = PimProduct.objects.filter(number__iexact=sku, brand_id=brand_id).order_by('pk').first()
    if product is not None:
        return product
    try:
        with transaction.atomic():
            return PimProduct.objects.create(number=sku, brand_id=brand_id, name=name)
    except IntegrityError:
        return PimProduct.objects.get(number__iexact=sku, brand_id=brand_id)


_ROW_BRAND = object()


def ensure_product(main_product, brand_id=_ROW_BRAND) -> bool:
    """Put an unlinked MainProduct on the Product of its sku and brand (resolve_product).

    Every path that writes a MainProduct by hand (the create modal, the admin,
    its import) goes through here, so a row never waits for the nightly
    reindex to become visible on /products/. brand_id defaults to the row's
    price-list brand (row_brand_id) — None for a hand-made row, which then
    gets a Product of its own. An existing link is kept — moving a row is
    MainProductMoveView's job. Returns whether the row is linked afterwards.
    """
    if main_product.product_id:
        return True
    if not main_product.sku or len(main_product.sku.strip()) > PRODUCT_NUMBER_MAX_LENGTH:
        return False
    if brand_id is _ROW_BRAND:
        brand_id = row_brand_id(main_product)
    product = resolve_product(main_product.sku, brand_id, main_product.name)
    MainProduct.objects.filter(pk=main_product.pk).update(product=product)
    main_product.product = product
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
    except SoftTimeLimitExceeded:
        raise
    except httpx.HTTPStatusError as exc:
        _record_pim_error("get_pim_data", exc, int((time.monotonic() - t0) * 1000))
        return None, exc.response.status_code == 404
    except Exception as exc:
        _record_pim_error("get_pim_data", exc, int((time.monotonic() - t0) * 1000))
        return None, False


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
        return data
    if not_found:
        cache.delete(cache_key)
        return None
    return cache.get(cache_key)


# Outcomes of one _search_pim_product_id() call.
_SEARCH_FOUND = "found"
_SEARCH_ABSENT = "absent"
_SEARCH_AMBIGUOUS = "ambiguous"
_SEARCH_ERROR = "error"


class PimScanError(RuntimeError):
    """A reindex batch ended with PIM searches unanswered or pushes rejected."""


def _search_pim_product_id(number: str, brand_pim_id: str | None = None) -> tuple[str | None, str]:
    """Find the PIM `Product` with this number and brand — returns (id, outcome).

    Only reindex calls this, to fill a new PriceManagerProduct's productId; the
    render path never searches PIM. `number` must be non-empty: Where.get()
    drops the value key when it is None (pim_api/__init__.py:24-25), so the
    request would otherwise go out as an unconstrained match.

    PIM is unique by (number, brand) since 2026-10-06, so a number alone can
    name several cards. The brand is matched on our side, from `brandId` in
    the same answer (list mode returns it only when selected): a branded
    Product matches the card of its brand, a brandless one only a brandless
    card. A brandless Product is never bound to a branded card by number
    alone — the brand would then come from PIM by guess.

    The search must stay `equals`, not `like`: AtroPIM passes a `like` value
    straight into SQL LIKE, so `_` matches any single character and `%`
    matches anything. Verified against the live API — `like '2001_-04_z01'`
    returns the product numbered `20015-04_z01` — and PIM numbers routinely
    contain `_` while sku is supplier-supplied.

    `outcome` is one of the _SEARCH_* constants. Callers must keep
    _SEARCH_ERROR apart from the rest: an error learned nothing, so pushing
    then would create the PMP without a productId the search could have found.
    Several cards of the same brand come back as _SEARCH_AMBIGUOUS and link
    none of them.
    """
    t0 = time.monotonic()
    try:
        result = site.get(
            EntityList(
                name='Product',
                select=['id', 'brandId'],
                where=[Where(attribute='number', type='equals', value=number)],
            )
        )
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:
        _record_pim_error("_search_pim_product_id", exc, int((time.monotonic() - t0) * 1000))
        return None, _SEARCH_ERROR

    pim_ids = [
        item.get('id') for item in result.get('list', [])
        if item.get('id') and (item.get('brandId') or None) == brand_pim_id
    ]
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
    """Return PIM data for a MainProduct through its local Product.

    Never links, creates or pushes anything — an unlinked row, or one whose
    Product has no pim_id yet, simply has no PIM data until reindex runs. It
    used to link an unlinked row to the Product numbered like its sku; with
    (number, brand) identity a number alone no longer names one Product.
    """
    return get_pim_data(_pim_id_of(product), refresh=refresh)


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
        except SoftTimeLimitExceeded:
            raise
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
#
# Исключение — публичные ссылки PIM (сущность Sharing, /sharings/<id>.<ext>):
# они открываются анонимно (проверено 2026-10-12), и такие фото браузер берёт
# у PIM сам, прокси для них — только запасной путь (product.ProductPhoto).

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


def pim_public_url(link) -> str | None:
    """Публичная ссылка PIM (Sharing.link) в виде, пригодном для <img src>, либо None.

    PIM отдаёт её без схемы («pim.tirado.kz/sharings/…»), как и downloadUrl.
    Принимается только https на хосте PIM: адрес приходит из данных PIM и
    уходит в разметку как есть, и чужой хост здесь — это картинка с чужого
    сервера в нашем интерфейсе.
    """
    url = _absolute_pim_url(link)
    if not url or not _on_pim_host(url) or len(url) > 500:
        return None
    return url


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

    Rows without a supplier are skipped: those are set rows, whose stock is
    how many sets the components make — product.services.set_rows recounts
    it at the end, from the stocks this run just wrote.

    Rows without a price-list row (no SupplierProduct at all) are skipped
    too, whatever their supplier: such a row was made by hand — a return, a
    bonus, leftover stock on «Свой склад», a retired set row — and its stock
    was typed in, so there is nothing to sync it from. A row whose price-list
    row merely lost its stock (the row vanished from the supplier's file)
    still goes to 0: there the price list does speak, and says "unknown".
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
        mps = MainProduct.objects.filter(pk__gte=chunk[0], pk__lte=chunk[-1], supplier__isnull=False).filter(
            Exists(SupplierProduct.objects.filter(main_product_id=OuterRef('pk'))),
        ).annotate(
            new_stock=Coalesce(Subquery(stock_subq, output_field=IntegerField()), Value(0), output_field=IntegerField()),
        ).filter(Q(stock__isnull=True) | ~Q(stock=F('new_stock')))
        if logs:
            mpls = [MainProductLog(main_product=mp, stock=mp.new_stock) for mp in mps]
            MainProductLog.objects.bulk_create(mpls, batch_size=batch_size)
        updated += mps.update(stock=F('new_stock'), stock_updated_at=now)
    from product.services.set_rows import sync_set_stocks
    updated += sync_set_stocks(logs=logs)
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


def link_unlinked_main_products(batch_size: int = 1000, main_product_ids=None) -> int:
    """Put every unlinked MainProduct that has a sku on its Product (number, brand).

    The bulk counterpart of ensure_product, with the same rule
    (resolve_product): a row whose price-list row names a brand
    (row_brand_subquery) goes to the Product with that number and brand,
    created if missing (name = the lowest-pk such row's name); a row without
    a brand gets a new Product of its own — brandless products sharing a
    number are different products. Existing links are never touched: a
    MainProduct already on a Product keeps it even if its sku now says
    otherwise.

    main_product_ids limits the pass to those rows — the copy-to-main import
    passes the rows it just touched, so a new supplier row lands on a Product
    at once instead of waiting for the nightly reindex. None is the whole
    table, as reindex runs it.

    Pure DB work, safe inside execute_locked_task's transaction. Each chunk
    locks its rows first: a row linked elsewhere meanwhile (a manual move) is
    skipped, and a brandless one never leaves an orphan Product behind. A sku
    longer than number's max_length can never be a number, so it stays
    unlinked and is counted in the log rather than failing the bulk_create.
    Returns how many MainProducts were linked.
    """
    from django.db import transaction

    scope = None if main_product_ids is None else list(main_product_ids)

    def unlinked():
        rows = MainProduct.objects.filter(product__isnull=True).exclude(sku__isnull=True).exclude(sku='')
        return rows if scope is None else rows.filter(pk__in=scope)

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
    pks = list(
        with_length.filter(sku_length__lte=PRODUCT_NUMBER_MAX_LENGTH).order_by('pk').values_list('pk', flat=True)
    )
    for start in range(0, len(pks), batch_size):
        with transaction.atomic():
            rows = list(
                MainProduct.objects.select_for_update(of=('self',))
                .filter(pk__in=pks[start:start + batch_size], product__isnull=True)
                .annotate(lower_sku=Lower('sku'), row_brand_id=row_brand_subquery())
                .order_by('pk')
                .values_list('pk', 'sku', 'lower_sku', 'name', 'row_brand_id')
            )
            _link_rows(rows)
    return before - unlinked().count()


def _link_rows(rows: list[tuple]) -> None:
    """link_unlinked_main_products for one locked chunk of (pk, sku, lower_sku, name, brand_id).

    Numbers are compared as Postgres lowers them (lower_sku comes from the
    same query), never as Python does, so a lookup key always meets the
    index's.
    """
    def trimmed(name):
        return (name or '')[:PRODUCT_NAME_MAX_LENGTH] or None

    links = {}
    brandless = [(pk, sku, name) for pk, sku, _, name, brand_id in rows if brand_id is None]
    if brandless:
        created = PimProduct.objects.bulk_create(
            [PimProduct(number=sku, name=trimmed(name)) for _, sku, name in brandless])
        links.update({pk: product.pk for (pk, _, _), product in zip(brandless, created)})

    branded = [row for row in rows if row[4] is not None]
    if branded:
        def existing():
            found = {}
            for pk, lower_number, brand_id in (
                PimProduct.objects.annotate(lower_number=Lower('number'))
                .filter(lower_number__in={row[2] for row in branded}, brand_id__in={row[4] for row in branded})
                .order_by('pk').values_list('pk', 'lower_number', 'brand_id')
            ):
                found.setdefault((lower_number, brand_id), pk)
            return found

        found = existing()
        missing = {}
        for _, sku, lower_sku, name, brand_id in branded:
            if (lower_sku, brand_id) not in found:
                missing.setdefault((lower_sku, brand_id), PimProduct(number=sku, name=trimmed(name), brand_id=brand_id))
        if missing:
            # A pair created since `found` was read is simply the Product
            # this row belongs to; the re-read picks it up.
            PimProduct.objects.bulk_create(list(missing.values()), ignore_conflicts=True)
            found = existing()
        for pk, _, lower_sku, _, brand_id in branded:
            if (lower_sku, brand_id) in found:
                links[pk] = found[(lower_sku, brand_id)]

    MainProduct.objects.bulk_update(
        [MainProduct(pk=pk, product_id=product_id) for pk, product_id in links.items()],
        fields=['product'], batch_size=1000,
    )


def iter_unpushed_product_pk_batches(batch_size: int = 1000):
    """Yield pks of local Products still waiting for a PriceManagerProduct, chunked.

    Waiting means pim_id NULL and at least one MainProduct — the PMP takes
    its name and description from one, and a Product nothing links to has no
    business in PIM. Used by
    reindex_pim_ids_task to fan out one reindex_pim_ids_batch_task per chunk.
    """
    pks = list(
        PimProduct.objects
        .filter(pim_id__isnull=True, main_products__isnull=False)
        .order_by('pk')
        .values_list('pk', flat=True)
        .distinct()
    )
    for start in range(0, len(pks), batch_size):
        yield pks[start:start + batch_size]


# Products searched, then pushed and stored, per upsertAsync job. Far below a
# reindex batch (1000 pks), so a batch the soft time limit cuts short keeps
# every chunk it stored before the cut. A small job is also less likely to
# outrun upsert_async's 60 s poll deadline, which skips the whole chunk.
PIM_PUSH_CHUNK_SIZE = 100


def _push_pim_links(targets: list) -> tuple[int, int]:
    """upsertAsync `targets` — [(Product, payload), ...] — as one job of
    PriceManagerProduct records and store each returned id as that Product's pim_id.

    A job whose transport/timeout/job call errors, or whose result has the
    wrong shape or length, is recorded via _record_pim_error and stores
    nothing: results are tied back to Products only by position, so a short
    or malformed list must never be zipped. Celery's SoftTimeLimitExceeded is
    the exception: it is re-raised, unrecorded, so the batch task ends as an
    error row before the hard limit SIGKILLs it.

    PIM matches an upsert on the PMP's unique field, platformID (our pk): a
    record that has it answers NotModified/Updated with its id — how a PMP
    whose id was lost gets it back. PMP.number is not unique since
    2026-10-13, so Products sharing a number each get their own PMP. A
    rejected item (a Failed status inside a job that still ends as Success)
    is logged and recorded, never placed on another Product's PMP: the old
    take-over by number would now hand one Product's PMP to another every
    night. Returns (linked, rejected).
    """
    if not targets:
        return 0, 0
    items = [{'entity': PIM_LINK_ENTITY, 'payload': payload} for _, payload in targets]
    t0 = time.monotonic()
    try:
        results = _upsert_async(site, items)
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:
        _record_pim_error('push_pim_links', exc, int((time.monotonic() - t0) * 1000))
        return 0, 0
    if not isinstance(results, list) or not all(isinstance(r, dict) for r in results):
        _record_pim_error(
            'push_pim_links',
            Exception(f'unexpected upsertAsync result shape: {results!r:.500}'),
            int((time.monotonic() - t0) * 1000),
        )
        return 0, 0
    if len(results) != len(targets):
        _record_pim_error(
            'push_pim_links',
            Exception(f'result count {len(results)} != item count {len(targets)}'),
            int((time.monotonic() - t0) * 1000),
        )
        return 0, 0

    linked = []
    rejected = []
    for (product, payload), result in zip(targets, results):
        pim_id = result.get('id')
        if result.get('status') == 'Failed' or not pim_id:
            rejected.append(result)
            continue
        product.pim_id = pim_id
        linked.append(product)
    if rejected:
        error = Exception(
            f'PIM отклонил {len(rejected)} из {len(targets)} товаров; '
            f'первый ответ: {rejected[0]!r:.500}'
        )
        logger.error('push_pim_links: %s', error)
        _record_pim_error('push_pim_links', error, int((time.monotonic() - t0) * 1000))
    if linked:
        # A PMP id may still be stored on a Product it no longer belongs
        # to (taken over before 2026-10-13, or a pk reused by another
        # environment); PIM gave it to this one, so the other loses it
        # here too (and is pushed afresh next run) rather than tripping
        # pim_id's unique constraint.
        PimProduct.objects.filter(pim_id__in=[p.pim_id for p in linked]).exclude(
            pk__in=[p.pk for p in linked]
        ).update(pim_id=None)
        PimProduct.objects.bulk_update(linked, fields=['pim_id'])
    return len(linked), len(rejected)


def push_pim_links(pks: list[int], delay: float = 0.5, chunk_size: int = PIM_PUSH_CHUNK_SIZE) -> int:
    """Create the PriceManagerProduct for one batch of local Products and store its id as pim_id.

    For each Product still without a pim_id: search the PIM Product by
    number and brand, then push {platformID: our pk, number, name, description}
    — plus productId when the search found exactly one. An ambiguous search pushes
    without productId, leaving PIM staff to pick the product; a failed search
    skips the Product, since pushing then would drop a productId the search
    might have found. The key is left out rather than sent as null when there
    is no match, so a push never clears a link PIM staff already set.

    Works in chunks of `chunk_size` Products: search the chunk, push it as one
    upsertAsync job and store its pim_ids, then go on to the next chunk.
    Runs as reindex_pim_ids_batch_task with atomic=False, so each chunk's
    writes commit before the next chunk's searches instead of idling a
    transaction across the PIM calls. Safe to resume: a Product that got its
    pim_id drops out of the next run's batches, and a repeat push of a PMP
    whose id was never saved answers with that id.
    Raises PimScanError after its last chunk if any search went unanswered or
    any push stayed rejected, so the batch is recorded as an error, not a
    success. The soft time limit is not an unanswered search:
    SoftTimeLimitExceeded propagates from wherever it lands, and the chunks
    stored before it stay stored, so a batch too slow for its limit still
    moves forward by those chunks every run.
    """
    products = list(
        PimProduct.objects.filter(pk__in=pks, pim_id__isnull=True).select_related('brand').order_by('pk')
    )
    if not products:
        return 0
    # Описание — из строки прайса поставщика, а не из MainProduct: своё
    # description у MainProduct удалено в Phase 2b, а копировалось оно ровно
    # отсюда (copy-to-main), так что PIM получает то же, что и раньше.
    first_main_product = {}
    for product_id, name, description in (
        MainProduct.objects.filter(product_id__in=[p.pk for p in products])
        .order_by('product_id', 'pk')
        .values_list('product_id', 'name', 'supplierproducts__description')
    ):
        first_main_product.setdefault(product_id, (name, description))

    linked = rejected = unanswered = 0
    # Chunked by Products searched, not by pushes collected, so a run of
    # unanswered searches cannot hold back the push of the answered ones.
    for start in range(0, len(products), chunk_size):
        targets = []
        for product in products[start:start + chunk_size]:
            if product.pk not in first_main_product:
                continue
            pim_product_id, outcome = _search_pim_product_id(
                product.number, product.brand.pim_id if product.brand_id else None)
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

        chunk_linked, chunk_rejected = _push_pim_links(targets)
        linked += chunk_linked
        rejected += chunk_rejected

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
