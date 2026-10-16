"""Фото товаров из PIM: все файлы товара (ProductFile) и их публичные ссылки (Sharing).

В raw_data товара PIM кладёт только mainImageId, поэтому всё остальное
зеркалируется в ProductPhoto отдельным ночным проходом
(product.refresh_product_photos). Отрисовка в сеть не ходит: страница берёт
public_url, если он есть, а иначе — наш прокси (pim_image_url), как было до
публичных ссылок.

Проход идёт партиями товаров PIM (BATCH_SIZE). Одной задачей полный проход
шёл около часа и не укладывался в лимит воркера. Партия же самодостаточна:
все файлы своих товаров (ProductFile productId in), их ссылки и одна
транзакция записи. Поэтому каждая партия сверяет свои товары полностью — и
узнаёт об отвязанных фото, — а упавшая не трогает чужие. Ночная задача
(plan_photo_batches) только раздаёт партии и делает то, что можно без них:
стирает фото товаров, отвязанных от PIM, а по будням ставит новые ссылки
(Sharing по createdAt) уже заведённым строкам.

Ссылки по будням — инкрементально: новые (createdAt) плюс ссылки файлов,
впервые появившихся у товаров партии. По воскресеньям (full=True) партия
читает Sharing всех своих файлов и стирает ссылки, которые PIM отозвал. До
этого отозванную ссылку подменяет на прокси сам браузер
(static/js/pim-photo-fallback.js).

Цена на живом PIM: ProductFile productId in [100] — ~1,1 с, Sharing fileId
in [100] — ~2,1 с (2026-10-16). Сплошной скан дешевле на строку (ProductFile
~1,5 с, Sharing ~8,4 с на 1000 строк, 2026-10-12: ~12 и ~41 минута целиком),
но это одна задача на час.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone as dt_timezone

from django.db import transaction
from django.db.models.fields.json import KT
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from pim_api import Asc, EntityList, Ordering, Where

from .. import pim_client
from ..models import Product, ProductPhoto

logger = logging.getLogger(__name__)

TASK_NAME = 'product.refresh_product_photos'

PAGE_SIZE = 1000
# Отбор productId/fileId in [...] уходит в строку запроса; на 200 uuid PIM
# отвечает 414 URI Too Long, 100 проходят (см. pim_api.FlatEntityList).
ID_CHUNK = 100
# Товаров PIM в партии. По будням партия — ~10 запросов ProductFile, в
# воскресенье ещё ~30 запросов Sharing: около минуты, далеко от лимита.
BATCH_SIZE = 1000
WRITE_CHUNK = 2000
# createdAt в PIM и started_at прошлого прогона могут жить в разных часовых
# поясах, а ссылку могли создать, пока прошлый прогон шёл. Сутки нахлёста
# покрывают и то и другое; повторно найденная ссылка ничего не меняет.
SHARING_OVERLAP = timedelta(days=1)

# В ProductFile лежат не только фото — у товара бывают инструкции и
# сертификаты. Тип файла список не отдаёт, поэтому отбор — по расширению
# имени: карусель из PDF показала бы битые картинки, а прокси их и не отдаёт
# (fetch_pim_image принимает только image/*).
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.svg', '.avif')

PRODUCT_FILE_FIELDS = ['productId', 'fileId', 'fileName', 'isMainImage', 'sorting']
SHARING_FIELDS = ['fileId', 'link', 'active', 'available', 'validTill']


# --- отрисовка ---------------------------------------------------------------

def photo_sources(pim_file_id: str, public_url: str = '') -> dict | None:
    """Адреса одного фото для <img>: src и увеличенный, каждый со своим запасным.

    С публичной ссылкой оба адреса — она (PIM отдаёт по ней оригинал, превью
    у ссылки нет), запасные — наш прокси. Без неё — прокси, запасных нет.
    None — у файла негодный id и показать его нечем.
    """
    from main_product_manager.utils import pim_image_url

    medium = pim_image_url(pim_file_id)
    large = pim_image_url(pim_file_id, 'large')
    if public_url:
        return {'src': public_url, 'fallback': medium or '', 'zoom': public_url, 'zoom_fallback': large or ''}
    if not medium:
        return None
    return {'src': medium, 'fallback': '', 'zoom': large, 'zoom_fallback': ''}


def product_photos(product: Product) -> list[dict]:
    """Фото товара по порядку показа, главное первым.

    Из ProductPhoto (предзагрузите photos, иначе это запрос на товар). Пока
    ночной проход их не завёл — новый товар, — одно главное фото по
    raw_data['mainImageId'] через прокси, как было до ProductPhoto.
    """
    photos = list(product.photos.all()) if product.pk else []
    if photos:
        sources = (photo_sources(photo.pim_file_id, photo.public_url) for photo in photos)
        return [source for source in sources if source]
    data = product.raw_data or {}
    main = photo_sources(data.get('mainImageId') or data.get('imageId'))
    return [main] if main else []


# --- чтение PIM --------------------------------------------------------------

def _iter_pages(name: str, fields: list[str], where: list[Where] | None = None):
    """Все строки списка PIM — страницами по id (keyset), а не по offset.

    Скан ProductFile идёт минуты, и PIM в это время живёт: файлы привязывают
    и отвязывают. Offset после удаления строки сдвигает страницы, и следующая
    строка молча пропускается — товар на сутки потерял бы фото. Отбор
    «id greaterThan последнего» так не сдвигается: удалённая строка просто не
    приходит, новая — приходит в конце (id в PIM — UUIDv7, растут со временем).
    Ошибка PIM поднимается наверх, до какой-либо записи в базу.
    """
    last_id = None
    while True:
        conditions = list(where or [])
        if last_id:
            conditions.append(Where(attribute='id', type='greaterThan', value=last_id))
        page = pim_client.site.get(
            EntityList(name=name, select=['id', *fields], where=conditions or None,
                       ordering=Ordering(sortBy='id', asc=Asc.ASC), maxSize=PAGE_SIZE),
            timeout=120)
        rows = page.get('list') or []
        yield from rows
        if len(rows) < PAGE_SIZE:
            return
        last_id = rows[-1].get('id')
        if not last_id:
            raise RuntimeError(f'photos: PIM отдал строку {name} без id — дальше страницы не взять')


def _is_image(file_name: str | None) -> bool:
    return (file_name or '').lower().endswith(IMAGE_EXTENSIONS)


def _sorting(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _linked_products():
    """Product, у которых есть товар PIM (raw_data['id']), — с его id в pim_product_id."""
    return (Product.objects.annotate(pim_product_id=KT('raw_data__id'))
            .filter(pim_product_id__isnull=False).exclude(pim_product_id=''))


def _local_products(pks=None) -> dict[str, list[int]]:
    """Id товара PIM → наши Product на нём (их бывает несколько, см. Product.name).

    pks — только эти Product (партия); None — все.
    """
    products = defaultdict(list)
    rows = _linked_products()
    if pks is not None:
        rows = rows.filter(pk__in=pks)
    for pk, pim_product_id in rows.values_list('pk', 'pim_product_id').iterator(chunk_size=5000):
        products[pim_product_id].append(pk)
    return products


def _desired_photos(products: dict[str, list[int]]) -> dict[int, list[tuple[str, bool]]]:
    """pk товара → [(id файла, главное)] в порядке показа — по ProductFile этих товаров PIM."""
    files = defaultdict(list)
    product_ids = sorted(products)
    for start in range(0, len(product_ids), ID_CHUNK):
        chunk = product_ids[start:start + ID_CHUNK]
        for row in _iter_pages('ProductFile', PRODUCT_FILE_FIELDS,
                               [Where(attribute='productId', type='in', value=chunk)]):
            product_id, file_id = row.get('productId'), row.get('fileId')
            if product_id not in products or not file_id or not _is_image(row.get('fileName')):
                continue
            is_main = bool(row.get('isMainImage'))
            files[product_id].append(
                (not is_main, _sorting(row.get('sorting')), row.get('fileName') or '', file_id))

    desired = {}
    for product_id, entries in files.items():
        entries.sort()
        ordered, seen = [], set()
        for not_main, _, _, file_id in entries:
            if file_id not in seen:
                seen.add(file_id)
                ordered.append((file_id, not not_main))
        for pk in products[product_id]:
            desired[pk] = ordered
    return desired


def _as_aware(value: datetime) -> datetime:
    return value if timezone.is_aware(value) else value.replace(tzinfo=dt_timezone.utc)


def _usable_link(row: dict, now: datetime) -> str | None:
    """Ссылка из строки Sharing, если по ней сейчас откроется файл.

    Отсутствие active/available в ответе — «не знаем», а не «выключена»:
    списочный режим PIM молча теряет поля, и строгая проверка обнулила бы
    все ссылки разом.
    """
    from main_product_manager.utils import pim_public_url

    if row.get('active') is False or row.get('available') is False:
        return None
    valid_till = parse_datetime(row.get('validTill') or '')
    if valid_till and _as_aware(valid_till) <= now:
        return None
    return pim_public_url(row.get('link'))


def _collect_links(rows, wanted: set[str] | None = None) -> dict[str, str]:
    now = timezone.now()
    links = {}
    for row in rows:
        file_id = row.get('fileId')
        if not file_id or file_id in links or (wanted is not None and file_id not in wanted):
            continue
        link = _usable_link(row, now)
        if link:
            links[file_id] = link
    return links


def _links_created_since(since: datetime) -> dict[str, str]:
    stamp = _as_aware(since).astimezone(dt_timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    return _collect_links(_iter_pages(
        'Sharing', SHARING_FIELDS,
        [Where(attribute='createdAt', type='greaterThanOrEquals', value=stamp)]))


def _links_for_files(file_ids) -> dict[str, str]:
    file_ids = sorted(file_ids)
    links = {}
    for start in range(0, len(file_ids), ID_CHUNK):
        chunk = file_ids[start:start + ID_CHUNK]
        links.update(_collect_links(_iter_pages(
            'Sharing', SHARING_FIELDS, [Where(attribute='fileId', type='in', value=chunk)])))
    return links


def last_successful_run() -> datetime | None:
    from core.models import TaskRunHistory

    run = (TaskRunHistory.objects.filter(task_name=TASK_NAME, status='success')
           .order_by('-started_at').first())
    return run.started_at if run else None


# --- запись ------------------------------------------------------------------

def _chunks(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _plan_rows(desired: dict[int, list[tuple[str, bool]]], pks: list[int]):
    """Что сделать с ProductPhoto товаров pks, чтобы он совпал с desired, — без записи.

    Возвращает (создать, обновить, удалить) кортежами, а не моделями: экземпляры
    моделей заняли бы в памяти воркера в разы больше.

    Товар из pks, которого нет в desired, теряет все фото: в PIM у него их
    больше нет, или он отвязан от товара PIM. Фото товаров не из pks не
    трогаются: это чужая партия.
    """
    creates, updates, deletes = [], [], []
    for chunk in _chunks(sorted(set(pks)), WRITE_CHUNK):
        existing = defaultdict(dict)
        rows = ProductPhoto.objects.filter(product_id__in=chunk).values_list(
            'pk', 'product_id', 'pim_file_id', 'position', 'is_main')
        for photo_pk, product_pk, file_id, position, is_main in rows:
            existing[product_pk][file_id] = (photo_pk, position, is_main)
        for pk in chunk:
            wanted = desired.get(pk, [])
            have = existing.get(pk, {})
            wanted_ids = {file_id for file_id, _ in wanted}
            deletes += [row[0] for file_id, row in have.items() if file_id not in wanted_ids]
            for position, (file_id, is_main) in enumerate(wanted):
                row = have.get(file_id)
                if row is None:
                    creates.append((pk, file_id, position, is_main))
                elif row[1:] != (position, is_main):
                    updates.append((row[0], position, is_main))
    return creates, updates, deletes


def _write_rows(creates, updates, deletes) -> int:
    """Пишет план _plan_rows. Возвращает число созданных строк.

    Товар, удалённый, пока шёл скан, пропускается: его строка упала бы на
    внешнем ключе и откатила бы весь ночной прогон.
    """
    for chunk in _chunks(deletes, WRITE_CHUNK):
        ProductPhoto.objects.filter(pk__in=chunk).delete()
    created = 0
    for chunk in _chunks(creates, WRITE_CHUNK):
        alive = set(Product.objects.filter(pk__in={row[0] for row in chunk}).values_list('pk', flat=True))
        photos = [ProductPhoto(product_id=pk, pim_file_id=file_id, position=position, is_main=is_main)
                  for pk, file_id, position, is_main in chunk if pk in alive]
        ProductPhoto.objects.bulk_create(photos, batch_size=1000)
        created += len(photos)
    for chunk in _chunks(updates, WRITE_CHUNK):
        ProductPhoto.objects.bulk_update(
            [ProductPhoto(pk=pk, position=position, is_main=is_main) for pk, position, is_main in chunk],
            ['position', 'is_main'], batch_size=1000)
    return created


def _apply_links(links: dict[str, str], rows, clear_missing: bool = False) -> int:
    """Ставит public_url строкам rows по id файла. Возвращает число изменённых строк.

    clear_missing — только для полного прохода партии: тогда links — все
    действующие ссылки её файлов, и строка из rows, которой в нём нет, ссылку
    потеряла. Поэтому rows — строки самой партии: шире — и стёрлись бы ссылки
    чужих. Инкрементальный проход видит лишь новые ссылки и ничего не стирает.
    """
    if not clear_missing:
        if not links:
            return 0
        rows = rows.filter(pim_file_id__in=list(links))
    changed = []
    for pk, file_id, current in rows.values_list('pk', 'pim_file_id', 'public_url').iterator(chunk_size=5000):
        url = links.get(file_id, '' if clear_missing else current)
        if url != current:
            changed.append(ProductPhoto(pk=pk, public_url=url))
    for chunk in _chunks(changed, WRITE_CHUNK):
        ProductPhoto.objects.bulk_update(chunk, ['public_url'], batch_size=1000)
    return len(changed)


def plan_photo_batches(full: bool = False, since: datetime | None = None) -> dict:
    """Ночной проход, раздача: партии товаров и то, что делается без них.

    Партия — pk наших Product на BATCH_SIZE товарах PIM; все Product одного
    товара PIM попадают в одну партию. Здесь же:
    - стираются фото товаров, отвязанных от PIM (raw_data без id): ни в одну
      партию они не попадут;
    - по будням — ссылки, созданные после since минус SHARING_OVERLAP,
      ставятся уже заведённым строкам. Ссылки файлов, которых ещё нет, найдёт
      партия.

    since=None при full=False — успешного прогона ещё не было, и проход
    полный. Сначала чтение PIM, потом короткая транзакция: сбой PIM не пишет
    ничего.
    """
    full = full or since is None
    links = {} if full else _links_created_since(since - SHARING_OVERLAP)
    products = _local_products()
    pim_ids = sorted(products)
    batches = [sorted(pk for pim_id in pim_ids[start:start + BATCH_SIZE] for pk in products[pim_id])
               for start in range(0, len(pim_ids), BATCH_SIZE)]

    with transaction.atomic():
        deleted, _ = ProductPhoto.objects.exclude(product_id__in=_linked_products().values('pk')).delete()
        linked = _apply_links(links, ProductPhoto.objects.all())
    stats = {'batches': batches, 'full': full, 'products': len(pim_ids), 'deleted': deleted, 'links': linked}
    logger.info('refresh_product_photos: партий %s, товаров PIM %s, полный %s, '
                'стёрто фото отвязанных товаров %s, новых ссылок %s',
                len(batches), len(pim_ids), full, deleted, linked)
    return stats


def refresh_photo_batch(pks: list[int], full: bool = False) -> dict:
    """Одна партия: фото товаров pks и их публичные ссылки.

    full=True — ссылки всех файлов партии, и строки, чьих ссылок больше нет,
    ссылку теряют. Иначе — только ссылки файлов, впервые появившихся у
    товаров: новые ссылки старых файлов ставит раздача (plan_photo_batches).

    Сначала всё читается из PIM, включая ссылки файлов новых строк, и только
    потом одной транзакцией пишется база. Сбой PIM на любом шаге не пишет
    ничего, и следующий прогон начинает с того же места. Запиши мы строки до
    поиска их ссылок, упавший поиск оставил бы их без ссылок до воскресенья:
    на следующую ночь эти строки уже не новые, а ссылки старше водяного знака.
    """
    desired = _desired_photos(_local_products(pks))
    wanted = {file_id for files in desired.values() for file_id, _ in files}
    creates, updates, deletes = _plan_rows(desired, pks)
    links = _links_for_files(wanted if full else {file_id for _, file_id, _, _ in creates})

    with transaction.atomic():
        created = _write_rows(creates, updates, deletes)
        linked = _apply_links({k: v for k, v in links.items() if k in wanted},
                              ProductPhoto.objects.filter(product_id__in=pks), clear_missing=full)
    stats = {'created': created, 'updated': len(updates), 'deleted': len(deletes), 'links': linked,
             'full': full, 'products': len(desired), 'files': len(wanted), 'linked_files': len(links)}
    logger.info('refresh_photo_batch %s-%s: %s', pks[0], pks[-1], stats)
    return stats
