from __future__ import annotations

import logging
import time

from django.db.models.fields.json import KT
from django.db.models.functions import Lower
from django.utils.dateparse import parse_datetime
from pim_api import Entity, EntityList, Where, fetch_list
from supplier_product_manager.models import SupplierProduct

from .. import pim_client
from ..models import Brand, Category, Product
from .brands import inherit_product_brands

# Поля товара PIM, которые нужны странице. Без явного select PIM не отдаёт ни
# categoriesIds, ни description — в списочном режиме они просто отсутствуют в
# ответе, молча, и зеркало наполняется товарами без категорий.
PRODUCT_SELECT = [
    'id', 'number', 'name', 'brandId', 'brandName',
    'description', 'longDescription', 'tag', 'categoriesIds',
]

# Сколько раз пытаться взять одну страницу каталога, прежде чем сдаться.
# Шесть попыток с удвоением дают в сумме около минуты ожидания. Четырёх (7
# секунд) не хватало: наблюдались и обрыв TLS на середине прохода, и
# httpx.ConnectError [Errno -2] Name or service not known — DNS у контейнера
# отваливается заметно дольше, чем на семь секунд.
_PAGE_RETRIES = 6

logger = logging.getLogger(__name__)


def _fetch_pim_link(pim_id: str) -> dict:
    """Raw GET PriceManagerProduct/{pim_id}. Raises on failure — callers decide how to handle it."""
    return pim_client.site.get(Entity(name='PriceManagerProduct', id=pim_id))


def _fetch_pim_product(product_id: str) -> dict:
    """Raw GET Product/{product_id}. Raises on failure — callers decide how to handle it."""
    return pim_client.site.get(Entity(name='Product', id=product_id))


def _fetch_pim_category(pim_category_id: str) -> dict:
    return pim_client.site.get(Entity(name='Category', id=pim_category_id))


def _ensure_pim_category(pim_category_id: str) -> Category | None:
    """Find or create the local Category matching a PIM category id.

    Walks up `parentsIds[0]` (the immediate parent — the local Category tree only
    supports a single parent) creating any missing ancestors too, so the full
    branch ends up marked in the tree. Returns None if the category can't be
    resolved (PIM error) rather than risk misplacing it under the wrong parent,
    so one bad id in a product's categoriesIds doesn't abort the whole sync.
    """
    if not pim_category_id:
        return None
    category = Category.objects.filter(pim_id=pim_category_id).first()
    if category:
        return category

    try:
        data = _fetch_pim_category(pim_category_id)
    except Exception:
        logger.warning('pim_sync: failed to fetch PIM category %s', pim_category_id, exc_info=True)
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
    return category


def _ensure_pim_brand(data: dict) -> Brand | None:
    """Find or create the Brand matching a PIM Product's brandId/brandName.

    Keyed on brandId, never on the name: PIM staff rename brands, and matching
    by name would fork one brand into two on the first rename. The name is kept
    in sync as a display label only. It replaces the supplier-side
    Manufacturer (and main_product_manager's _resolve_manufacturer, which
    filled it from PIM); both went in Phase 2b.
    """
    brand_id = data.get('brandId')
    if not brand_id:
        return None
    name = data.get('brandName') or brand_id
    brand, created = Brand.objects.get_or_create(pim_id=brand_id, defaults={'name': name})
    if not created and brand.name != name:
        brand.name = name
        brand.save(update_fields=['name'])
    return brand


def _adopting_product(link: dict, number: str) -> Product:
    """Local Product for a PMP no Product holds yet: its platformID, else its number, else new.

    platformID is our pk, so it names the Product exactly. The number is the
    fallback only while it is unambiguous: a number is not unique since
    (number, brand) identity, and of several Products waiting for a PMP none
    is more this one than the others. iexact — numbers compare
    case-insensitively.
    """
    try:
        pk = int(link.get('platformID') or '')
    except ValueError:
        pk = None
    if pk is not None:
        product = Product.objects.filter(pk=pk, pim_id__isnull=True).first()
        if product is not None:
            return product
    waiting = list(Product.objects.filter(number__iexact=number, pim_id__isnull=True)[:2])
    return waiting[0] if len(waiting) == 1 else Product(number=number)


def sync_product_from_pim(pim_id: str, data: dict | None = None) -> Product:
    """Persist PIM data onto the local Product whose PriceManagerProduct is `pim_id`.

    pim_id is a PriceManagerProduct id. The local Product is the one already
    holding it; failing that, one without a pim_id adopts it
    (_adopting_product: the PMP's platformID, else its number if only one
    Product waits with it); failing that, a new Product is created with both.

    `data` is the PIM Product that PMP points at, fetched through the PMP's
    productId unless given. It supplies name, raw_data and categoriesIds ->
    M2M. number is never taken from it: number is the local sku match key,
    and PIM staff may link the PMP to a Product numbered differently. A PMP
    not linked to a PIM Product yet leaves name/raw_data/categories as they are.

    Raises ValueError for an unknown PMP without a number. Lets IntegrityError
    (a race on the (number, brand) pair) and any PIM-fetch error propagate — it's
    the caller's job to decide how to surface them. Fetches happen before the
    first write, so a failed fetch leaves no half-made row behind.
    """
    link = None
    product = Product.objects.filter(pim_id=pim_id).first()
    if product is None:
        link = _fetch_pim_link(pim_id)
        number = (link.get('number') or '').strip()
        if not number:
            # number is required: a Product without one matches no sku and is
            # how one sku once ended up on two Products (product.0016).
            raise ValueError(f'PMP {pim_id} has no number — nothing to match a local Product by')
        product = _adopting_product(link, number)
        product.pim_id = pim_id
    if data is None:
        if link is None:
            link = _fetch_pim_link(pim_id)
        product_id = link.get('productId')
        data = _fetch_pim_product(product_id) if product_id else None
    if data is None:
        product.save()
        return product

    apply_pim_product(product, data)
    return product


def _pim_brand_for(product: Product, data: dict) -> Brand | None:
    """Бренд, который товар получает при синхронизации с PIM `data`.

    Бренд — половина идентичности товара (артикул, бренд), поэтому PIM его не
    стирает и не отбирает:
    - нет бренда в PIM — остаётся свой (например, бренд поставщика);
    - свой бренд не из PIM (не тот, что PIM прислал в прошлый раз) и бренд
      PIM другой — остаётся свой, расхождение — в лог;
    - пара (артикул, бренд PIM) уже у другого товара — бренд не ставится,
      конфликт — в лог: склеивают руками, переносом строк ГП.
    """
    current = product.brand if product.brand_id else None
    pim_brand = _ensure_pim_brand(data)
    if pim_brand is None or (current is not None and current.pk == pim_brand.pk):
        return current
    previous_pim_brand_id = (product.raw_data or {}).get('brandId')
    if current is not None and current.pim_id != previous_pim_brand_id:
        logger.warning('pim_sync: товар %s (%s) — бренд «%s» не из PIM, в PIM «%s»; оставлен свой',
                       product.pk, product.number, current.name, pim_brand.name)
        return current
    taken = (Product.objects.filter(number__iexact=product.number, brand=pim_brand)
             .exclude(pk=product.pk).values_list('pk', flat=True).first())
    if taken is not None:
        logger.warning('pim_sync: товар %s (%s) — бренд «%s» из PIM не поставлен: пара уже у товара %s',
                       product.pk, product.number, pim_brand.name, taken)
        return current
    return pim_brand


def apply_pim_product(product: Product, data: dict) -> None:
    """Записывает товар PIM `data` на `product` и сохраняет его.

    name, raw_data, бренд (_pim_brand_for), категории, затем поисковый вектор.
    number не трогает — это локальный ключ сопоставления. Общая часть
    sync_product_from_pim и синхронизации наборов (services/sets.py): набор
    приходит в зеркало не через PriceManagerProduct, но пишется так же.
    """
    brand_before = product.brand_id
    product.brand = _pim_brand_for(product, data)
    product.name = data.get('name') or None
    product.raw_data = data

    category_ids = data.get('categoriesIds') or []
    categories = [c for c in (_ensure_pim_category(cid) for cid in category_ids) if c]
    product.save()
    product.categories.set(categories)
    if product.brand_id != brand_before:
        # Строки прайса без заявки о бренде берут бренд товара.
        inherit_product_brands(SupplierProduct.objects.filter(main_product__product=product))
    # После save(), а не до: rebuild_search_vector() делает update() по pk, и до
    # первого сохранения у новой строки pk ещё нет. Вектор собирается из
    # raw_data, которые мы только что записали, — в PIM он не ходит.
    product.rebuild_search_vector()


def unsynced_products(refresh: bool = False):
    """Product-ы, которым нужен контент из PIM.

    Синхронизировать можно только строку, у которой уже есть pim_id: он и есть
    тот PriceManagerProduct, через который мы ходим за товаром. Заготовки без
    pim_id — работа reindex_pim_ids, не наша, и порядок здесь жёсткий:

        reindex_pim_ids (проставляет pim_id) -> этот бэкфилл -> вектор

    Признак «ни разу не синхронизировали» — пустой raw_data. Миграции 0005/0007
    оставляют заготовки именно такими: pim_id есть, а name, категории, бренд и
    вектор пустые.
    """
    queryset = Product.objects.filter(pim_id__isnull=False)
    return queryset if refresh else queryset.filter(raw_data={})


def iter_unsynced_product_pk_batches(batch_size: int = 500, refresh: bool = False):
    """pk-шки под бэкфилл, партиями. Порядок по pk — чтобы партии не пересекались."""
    pks = list(unsynced_products(refresh=refresh).order_by('pk').values_list('pk', flat=True))
    for start in range(0, len(pks), batch_size):
        yield pks[start:start + batch_size]


def sync_products(pks: list[int], delay: float = 0.5) -> int:
    """Синхронизирует партию Product-ов, возвращает число строк с контентом PIM.

    Ошибка на одном товаре не роняет партию: PIM отвечает по товару за раз, и
    один 404 или таймаут не повод потерять остальные 499. Та же логика, что у
    _ensure_pim_category с битым id категории. Сбойные строки останутся с
    пустым raw_data и попадут в следующий прогон — бэкфилл идемпотентен.

    PMP без productId — не успех: sync_product_from_pim сохраняет тогда одну
    связь, и raw_data остаётся пустым. Раньше такие считались синхронизированными,
    и история задач показывала успехом партии, в которых контент не получил
    почти никто.
    """
    synced = 0
    without_product = 0
    failed = 0
    for pim_id in (
        Product.objects.filter(pk__in=pks)
        .exclude(pim_id__isnull=True)
        .values_list('pim_id', flat=True)
    ):
        try:
            product = sync_product_from_pim(pim_id)
        except Exception:
            failed += 1
            logger.warning('pim_sync: не удалось синхронизировать PMP %s', pim_id, exc_info=True)
        else:
            if product.raw_data:
                synced += 1
            else:
                without_product += 1
        if delay:
            time.sleep(delay)
    logger.info(
        'pim_sync: партия завершена — с контентом %s, PMP без товара PIM %s, с ошибкой %s',
        synced, without_product, failed,
    )
    return synced


def _fetch_complete(query: EntityList, page_size: int) -> list[dict]:
    """fetch_list, который не терпит обрезанного ответа (как _fetch_all в sets)."""
    result = fetch_list(pim_client.site, query, page_size=page_size, timeout=120)
    if result.truncated:
        raise RuntimeError(
            f'pim_sync: PIM отдал {len(result.items)} из {result.total} строк {query.name} — '
            'список неполный, сверка остановлена')
    return result.items


def _changed_since(mirrored: str | None, current: str | None) -> bool:
    """Сдвинулось ли modifiedAt товара PIM с того, что лежит в зеркале.

    Строки сравниваются как даты: список и карточка PIM могут отдать одно
    время в разной записи. Без modifiedAt в списке сравнивать не с чем — это
    «не знаем», а не «изменился»: списочный режим PIM молча теряет поля, и
    тогда весь каталог каждую ночь уходил бы на перезагрузку.
    """
    if not current or mirrored == current:
        return False
    if not mirrored:
        return True
    parsed = parse_datetime(mirrored)
    return parsed is None or parsed != parse_datetime(current)


def stale_product_pks(page_size: int = 1000) -> list[int]:
    """pk товаров, чей контент в зеркале разошёлся с PIM.

    Бэкфилл берёт только raw_data={} и сам не запускается, поэтому зеркало
    застывает: PMP, которые сотрудники PIM привязали к товару позже, остаются
    без контента навсегда, а описание, дописанное в PIM, не доезжает никогда.
    Здесь вместо этого две выборки списком — все PMP (id → productId) и все
    товары PIM (id → modifiedAt), несколько сотен запросов, — и сравнение с тем,
    что лежит в raw_data. Устарела строка, у которой:

    - PMP теперь указывает на товар PIM, а в raw_data другой (или никакого) id —
      сюда попадают и ни разу не синхронизированные строки;
    - modifiedAt товара PIM не совпадает с тем, что мы сохранили.

    PMP без productId пропускается: забирать пока нечего, и ходить за ним
    каждую ночь — пустые запросы. Товары без pim_id (наборы, ещё не
    отправленные в PIM) сюда не попадают: наборы пишет services/sets.py.
    """
    product_ids = {
        row['id']: row.get('productId')
        for row in _fetch_complete(
            EntityList(name='PriceManagerProduct', select=['id', 'productId']), page_size)
    }
    modified = {
        row['id']: row.get('modifiedAt')
        for row in _fetch_complete(EntityList(name='Product', select=['id', 'modifiedAt']), page_size)
    }
    if modified and not any(modified.values()):
        logger.warning('pim_sync: список товаров PIM пришёл без modifiedAt — '
                       'правки в PIM этой ночью не сверяются, только новые привязки PMP')

    stale = []
    rows = (
        Product.objects.filter(pim_id__isnull=False)
        .annotate(mirrored_id=KT('raw_data__id'), mirrored_at=KT('raw_data__modifiedAt'))
        .order_by('pk')
        .values_list('pk', 'pim_id', 'mirrored_id', 'mirrored_at')
    )
    for pk, pim_id, mirrored_id, mirrored_at in rows.iterator(chunk_size=5000):
        product_id = product_ids.get(pim_id)
        if not product_id:
            continue
        if mirrored_id != product_id or _changed_since(mirrored_at, modified.get(product_id)):
            stale.append(pk)
    return stale


def sync_category_tree_from_pim(page_size: int = 200) -> dict:
    """Приводит локальное дерево категорий в соответствие с PIM целиком.

    Существует отдельно от _ensure_pim_category, потому что тот вызывается
    только когда на категорию сослался синхронизируемый товар, и НИКОГДА не
    обновляет уже найденную строку. Переименование категории в PIM так не
    доедет до зеркала никогда, а смена родителя тихо уводит товары в чужую
    ветку дерева, по которой categories_method потом разворачивает выбор.
    Пока зеркало было списком фасетов, это была косметика; теперь по нему
    фильтруют, поэтому расхождение надо чинить целенаправленно.

    Порядок вставки — от корней вниз: родитель обязан существовать раньше
    ребёнка, иначе MPTT некуда его подвесить.
    """
    listing = fetch_list(
        pim_client.site,
        EntityList(name='Category', select=['id', 'name', 'parentId']),
        page_size=page_size,
    )
    rows = {row['id']: row for row in listing.items if row.get('id')}

    ordered, seen = [], set()

    def visit(pim_id):
        if pim_id in seen or pim_id not in rows:
            return
        seen.add(pim_id)
        parent_id = rows[pim_id].get('parentId')
        if parent_id:
            visit(parent_id)
        ordered.append(pim_id)

    for pim_id in rows:
        visit(pim_id)

    local = {c.pim_id: c for c in Category.objects.exclude(pim_id__isnull=True)}
    created = renamed = reparented = 0

    for pim_id in ordered:
        row = rows[pim_id]
        name = row.get('name') or pim_id
        parent = local.get(row.get('parentId'))
        category = local.get(pim_id)

        if category is None:
            category = Category.objects.create(pim_id=pim_id, name=name, parent=parent)
            local[pim_id] = category
            created += 1
            continue

        if category.name != name:
            category.name = name
            category.save(update_fields=['name'])
            renamed += 1
        if category.parent_id != (parent.pk if parent else None):
            # move_to, а не присваивание parent: MPTT держит lft/rght/level, и
            # обычный save() их не пересчитает — дерево останется битым.
            category.move_to(parent, position='last-child')
            reparented += 1

    result = {
        'total': listing.total, 'created': created,
        'renamed': renamed, 'reparented': reparented,
    }
    logger.info('pim_sync: дерево категорий синхронизировано — %s', result)
    return result


def load_products_by_number(page_size: int = 1000, limit: int | None = None,
                            start_offset: int = 0, progress=None) -> dict:
    """Наполняет зеркало содержимым PIM, сопоставляя по number.

    Идёт постранично по товарам PIM и раскладывает их на локальные Product с
    тем же number. Это НЕ замена backfill_products_from_pim: тот ходит за
    каждым товаром через его PriceManagerProduct и нужен в бою, а этот
    вытаскивает каталог оптом и ничего в PIM не пишет. На 178k товаров разница
    между 179 запросами и 300 тысячами.

    Сопоставление по number законно: number локального Product — это
    MainProduct.sku, а привязка к PIM и строится по равенству sku и number.
    Но только для номера, который у нас один: с 2026-10-13 товар — пара
    (артикул, бренд), и номер нескольких товаров не говорит, какой из них
    этот товар PIM (а чужой бренд на нём нарушил бы уникальность пары).
    Регистр не важен ни здесь, ни при сравнении: «ABC-1» и «abc-1» у нас —
    один номер, как и в уникальности пары.

    В PIM номер не уникален — уникальна пара. Если на один локальный товар
    ложатся несколько товаров PIM, побеждает тот, чей бренд совпал с брендом
    товара, затем — точное совпадение регистра, затем — первый; порядок
    страниц не важен. Проигравшие идут в skipped, вместе с товарами PIM без
    локальной пары.

    Бренд — по правилам _pim_brand_for: PIM не стирает бренд товара и не
    отбирает бренд, пришедший не из PIM.
    """
    # Номер приводит к нижнему регистру Postgres, а не Python: так ключ
    # совпадает с ключом уникальности пары. Номер PIM опускает Python — где
    # они разойдутся, совпадение просто потеряется, а не ляжет не туда.
    held, shared = {}, set()
    for pk, lower_number, number, brand_pk, brand_pim_id, previous_pim_brand_id in (
        Product.objects.annotate(lower_number=Lower('number'), previous_pim_brand_id=KT('raw_data__brandId'))
        .values_list('pk', 'lower_number', 'number', 'brand_id', 'brand__pim_id', 'previous_pim_brand_id')
    ):
        if lower_number in held:
            shared.add(lower_number)
        held[lower_number] = (pk, number, brand_pk, brand_pim_id, previous_pim_brand_id)
    for lower_number in shared:
        del held[lower_number]
    # pk -> место товара PIM, который его наполнил: (бренд совпал, регистр совпал).
    filled = {}
    categories = {c.pim_id: c.pk for c in Category.objects.exclude(pim_id__isnull=True)}
    brands = {b.pim_id: b.pk for b in Brand.objects.all()}
    through = Product.categories.through

    matched = skipped = 0
    # Смещение, с которого продолжаем. Прогон по 178 тыс. товаров идёт минуты, и
    # если его прервали, начинать заново — это заново платить за уже пройденные
    # страницы. Перекрытие безвредно: раскладка идемпотентна.
    offset = start_offset
    total = 0

    while True:
        # Ретраи с отступом: прогон идёт минуты и держит соединение к PIM всё
        # это время, поэтому разрыв — не исключение, а ожидаемое событие.
        # Наблюдалось: httpx.ConnectError [SSL: UNEXPECTED_EOF_WHILE_READING]
        # на середине прохода. Без ретрая одна такая икота выбрасывает весь
        # прогон, включая уже разобранные страницы.
        response = None
        for attempt in range(_PAGE_RETRIES):
            try:
                response = pim_client.site.get(
                    EntityList(name='Product', select=PRODUCT_SELECT,
                               offset=offset, maxSize=page_size),
                    timeout=120,
                )
                break
            except Exception:
                if attempt == _PAGE_RETRIES - 1:
                    logger.error('pim_sync: страница offset=%s не далась за %s попыток',
                                 offset, _PAGE_RETRIES, exc_info=True)
                    raise
                wait = 2 ** attempt
                logger.warning('pim_sync: сбой на offset=%s, повтор через %sс', offset, wait,
                               exc_info=True)
                time.sleep(wait)

        total = int(response.get('total') or 0)
        batch = response.get('list') or []
        if not batch:
            break

        # По pk: товар, попавший на страницу дважды, попал бы в bulk_update
        # дважды, и победил бы первый (CASE WHEN), а не лучший.
        updates, links = {}, {}
        for row in batch:
            number = row.get('number') or ''
            brand_id = row.get('brandId')
            local = held.get(number.lower())
            if local is None:
                skipped += 1
                continue
            pk, local_number, brand_pk, brand_pim_id, previous_pim_brand_id = local
            rank = (bool(brand_id) and brand_id == brand_pim_id, number == local_number)
            if pk in filled:
                # Проигравший — этот или вытесненный им: matched + skipped
                # остаётся равным числу просмотренных.
                skipped += 1
                if rank <= filled[pk]:
                    continue
            else:
                matched += 1
            filled[pk] = rank

            if brand_id:
                if brand_id not in brands:
                    brand = Brand.objects.create(
                        pim_id=brand_id, name=row.get('brandName') or brand_id)
                    brands[brand_id] = brand.pk
                # Свой бренд не из PIM остаётся. Пару проверять не нужно: номер
                # у нас ровно у одного товара, другого с этой парой нет.
                if brand_pk is None or brand_pim_id == previous_pim_brand_id:
                    brand_pk = brands[brand_id]

            updates[pk] = Product(pk=pk, name=row.get('name') or None,
                                  raw_data=row, brand_id=brand_pk)
            links[pk] = [through(product_id=pk, category_id=categories[cid])
                         for cid in (row.get('categoriesIds') or []) if cid in categories]

        if updates:
            Product.objects.bulk_update(list(updates.values()), ['name', 'raw_data', 'brand'],
                                        batch_size=500)
        links = [link for product_links in links.values() for link in product_links]
        if links:
            through.objects.bulk_create(links, ignore_conflicts=True, batch_size=1000)

        offset += len(batch)
        if progress:
            progress(offset, total, matched)
        if limit is not None and offset >= limit:
            break
        if offset >= total:
            break

    result = {'pim_total': total, 'scanned': offset, 'matched': matched, 'skipped': skipped}
    logger.info('pim_sync: контент загружен — %s', result)
    return result
