"""Бренды: зеркало списка PIM, синонимы написаний поставщиков, слияние.

Первый шаг перехода на «товар = (бренд, артикул)» (2026-10-12). PIM — источник
брендов: здесь бренды только зеркалятся (sync_brands_from_pim) и создаются в
PIM по кнопке человека (create_pim_brand), никогда сами. Бренд из прайса
поставщика (SupplierProduct.brand_name) — заявка: она сводится к бренду PIM
синонимом (BrandAlias) или неявно — названием бренда PIM с тем же ключом
(models.brand_key). Чего свести не удалось, ждёт в окне «Бренды».

Сопоставленный бренд живёт на строке ПП (SupplierProduct.brand). Товару без
бренда PIM он достаётся, когда поставщики его товара не спорят
(adopt_supplier_brands, шаг 3 — «товар = (бренд, артикул)», 2026-10-13).
Строка, о бренде которой поставщик ничего не заявил, наоборот, берёт бренд
своего товара (inherit_product_brands, 2026-10-13).
"""
from __future__ import annotations

import difflib
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from django.contrib.postgres.search import SearchVectorField
from django.db import transaction
from django.db.models import Count, Exists, F, Min, OuterRef, Q, Subquery, Value
from django.db.models.expressions import RawSQL
from django.db.models.functions import Lower

from main_product_manager.models import MainProduct
from pim_api import Asc, EntityList, Ordering, fetch_list, upsert_async
from supplier_product_manager.models import Setting, SupplierProduct

from .. import pim_client
from ..models import Brand, BrandAlias, Product, brand_key

logger = logging.getLogger(__name__)

BRAND_SELECT = ['id', 'name', 'code', 'isActive']

# Сколько написаний класть в один brand_name IN (...).
_NAMES_CHUNK = 500

# Сколько примеров несопоставленных написаний называть в уведомлении импорта.
UNRESOLVED_EXAMPLES = 5


class PimBrandError(Exception):
    """Бренд в PIM создать не удалось; сообщение — для пользователя."""


class BrandMergeConflict(ValueError):
    """Слияние брендов дало бы два товара с одной парой (артикул, бренд); сообщение — для пользователя."""


# Сколько артикулов-двойников называть в отказе слияния брендов.
MERGE_CONFLICT_EXAMPLES = 5


class BrandIndex:
    """Ключ написания → бренд, одним проходом по брендам и синонимам.

    Синоним сильнее неявного совпадения с названием: им и чинят случай, когда
    у двух активных брендов PIM один ключ (дубль в PIM, STAYER/Stayer), — такой
    ключ без синонима не сводится никуда, потому что выбрать за человека
    нельзя. Неактивный бренд неявно не сопоставляется: его в PIM уже нет.
    """

    def __init__(self):
        self.by_key: dict[str, int | None] = {}
        self.ambiguous: set[str] = set()
        candidates = defaultdict(set)
        for pk, name in Brand.objects.filter(is_active=True).values_list('pk', 'name'):
            key = brand_key(name)
            if key:
                candidates[key].add(pk)
        for key, pks in candidates.items():
            if len(pks) == 1:
                self.by_key[key] = next(iter(pks))
            else:
                self.ambiguous.add(key)
        for key, brand_id in BrandAlias.objects.values_list('name_key', 'brand_id'):
            self.by_key[key] = brand_id
            self.ambiguous.discard(key)

    def lookup(self, name: str | None) -> tuple[bool, int | None]:
        """(сведено ли написание, id бренда). Сведено к None — «бренда нет».

        Написание, от которого после ключа ничего не осталось («-», «.»), —
        тоже «бренда нет», а не очередь.
        """
        key = brand_key(name)
        if not key:
            return True, None
        if key in self.by_key:
            return True, self.by_key[key]
        return False, None

    def is_ambiguous(self, name: str | None) -> bool:
        return brand_key(name) in self.ambiguous


@dataclass
class ResolutionStats:
    unresolved_rows: int = 0
    unresolved_names: list[str] = field(default_factory=list)


def _chunks(values: list, size: int = _NAMES_CHUNK):
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _inherit(rows) -> None:
    """Строкам rows — бренд товара их строки ГП; нет товара или бренда у него — никакого.

    rows — только строки без заявки поставщика. Два UPDATE, и только строкам,
    у которых бренд другой.
    """
    rows.filter(brand__isnull=False, main_product__product__brand__isnull=True).update(brand=None)
    (rows.filter(main_product__product__brand__isnull=False)
     .filter(Q(brand__isnull=True) | ~Q(brand=F('main_product__product__brand')))
     .update(brand_id=Subquery(
         MainProduct.objects.filter(pk=OuterRef('main_product_id')).values('product__brand')[:1])))


def inherit_product_brands(rows, index: BrandIndex | None = None) -> None:
    """Строкам ПП из rows, о бренде которых поставщик ничего не заявил, — бренд их товара.

    Заявки нет у строки без написания и у строки, написание которой значит
    «бренда нет» (синоним «игнорировать», одни разделители). Такая строка
    берёт бренд товара своей строки ГП: бренд строки — половина пары
    (артикул, бренд), и без него правка артикула или перенумерация увели бы
    строку на новый товар без бренда. Строку с несведённым написанием это не
    трогает — её решают в окне «Бренды».

    Правило держит apply_brand_resolution. Отдельно функцию зовут там, где у
    строки меняется товар или у товара бренд (перенос строки ГП, карточка
    товара, PIM, adopt_supplier_brands): строка получает бренд сразу, не
    дожидаясь ночного сопоставления.
    """
    names = list(rows.exclude(brand_name__isnull=True).values_list('brand_name', flat=True).distinct())
    no_brand = []
    if names:
        index = index or BrandIndex()
        no_brand = [name for name in names if index.lookup(name) == (True, None)]
    _inherit(rows.filter(Q(brand_name__isnull=True) | Q(brand_name__in=no_brand)))


def apply_brand_resolution(queryset, index: BrandIndex | None = None) -> ResolutionStats:
    """Проставить строкам ПП бренд: сведённую заявку поставщика, а без заявки — бренд товара.

    Один UPDATE на бренд (по пачкам написаний), и только строкам, у которых
    бренд другой, — ночной полный проход не переписывает весь прайс. update(),
    не save(): updated_at — время данных поставщика, а не сопоставления.
    Строки без написания или с написанием «бренда нет» берут бренд товара
    (inherit_product_brands); строки с несведённым написанием остаются без
    бренда.
    """
    index = index or BrandIndex()
    names = list(queryset.exclude(brand_name__isnull=True).values_list('brand_name', flat=True).distinct())
    targets: dict[int | None, list[str]] = defaultdict(list)
    unresolved: list[str] = []
    for name in names:
        found, brand_id = index.lookup(name)
        if found:
            targets[brand_id].append(name)
        else:
            unresolved.append(name)

    no_brand = targets.pop(None, [])
    for brand_id, chunk_names in targets.items():
        for chunk in _chunks(chunk_names):
            (queryset.filter(brand_name__in=chunk)
             .filter(Q(brand__isnull=True) | ~Q(brand_id=brand_id)).update(brand_id=brand_id))
    _inherit(queryset.filter(brand_name__isnull=True))
    for chunk in _chunks(no_brand):
        _inherit(queryset.filter(brand_name__in=chunk))

    stats = ResolutionStats(unresolved_names=sorted(unresolved))
    for chunk in _chunks(unresolved):
        rows = queryset.filter(brand_name__in=chunk)
        rows.filter(brand__isnull=False).update(brand=None)
        stats.unresolved_rows += rows.count()

    # Сведённый бренд поставщика может дать бренд товару без бренда — после
    # коммита и задачей: первый проход по всему каталогу не для запроса окна
    # «Бренды». Откат (--dry-run бэкфилла) задачу не отправит.
    from core.task_runner import dispatch_after_commit
    from ..tasks import adopt_supplier_brands_task
    dispatch_after_commit(adopt_supplier_brands_task)
    return stats


@dataclass
class AdoptionStats:
    adopted: int = 0
    # Строки прайса товара называют разные бренды или ждут сопоставления.
    disputed: int = 0
    # Пара (артикул, бренд) уже у другого товара.
    taken: int = 0


def adopt_supplier_brands() -> AdoptionStats:
    """Поставить товарам без бренда бренд их поставщиков — там, где спора нет.

    Товар — пара (артикул, бренд), и бренд товара — бренд PIM, а если в PIM
    его нет, то бренд поставщиков. Товар без бренда получает бренд X, когда:
    - хотя бы одна строка прайса его строк ГП сведена к X и ни одна — к
      другому бренду;
    - ни одна такая строка не ждёт сопоставления: несведённое написание — тоже
      заявка на бренд, может быть, на другой («игнорировать» — не заявка);
    - пары (артикул, X) нет у другого товара. Из нескольких товаров без
      бренда с одним артикулом, которым досталась бы одна пара, бренд
      получает старший по pk; остальные остаются без бренда и ждут ручного
      переноса строк ГП.

    Унаследованный бренд (inherit_product_brands) — не заявка и не голос.
    Поэтому проход начинается с того, что строки без заявки снова берут бренд
    своего товара — у товара без бренда никакого. Иначе строка, которую
    перенесли с товара с брендом, голосовала бы за прежний бренд. Строки
    товаров, получивших бренд, наследуют его сразу.

    Поисковый вектор дополняется названием бренда одним UPDATE на пачку, а не
    пересобирается: пересборка — запрос на товар, а первый проход ставит
    бренды десяткам тысяч товаров. Связь с PIM не трогается.
    """
    stats = AdoptionStats()
    index = BrandIndex()
    inherit_product_brands(SupplierProduct.objects.all(), index)
    pending_names = [
        name for name in SupplierProduct.objects.filter(brand__isnull=True, brand_name__isnull=False)
        .values_list('brand_name', flat=True).distinct()
        if not index.lookup(name)[0]
    ]
    supplier_rows = SupplierProduct.objects.filter(main_product__product=OuterRef('pk'))
    pending = (Exists(supplier_rows.filter(brand__isnull=True, brand_name__in=pending_names))
               if pending_names else Value(False))
    rows = (
        Product.objects.filter(brand__isnull=True)
        .filter(Exists(supplier_rows.filter(brand__isnull=False)))
        .annotate(
            lower_number=Lower('number'),
            brand_count=Count('main_products__supplierproducts__brand', distinct=True),
            supplier_brand=Min('main_products__supplierproducts__brand'),
            pending=pending,
        )
        .order_by('pk')
        .values_list('pk', 'lower_number', 'supplier_brand', 'brand_count', 'pending')
    )

    winners: dict[tuple[str, int], int] = {}
    candidates = 0
    for pk, lower_number, brand_id, brand_count, has_pending in rows:
        if brand_count > 1 or has_pending:
            stats.disputed += 1
            continue
        candidates += 1
        winners.setdefault((lower_number, brand_id), pk)
    for chunk in _chunks(list(winners)):
        held = set(
            Product.objects.filter(brand__isnull=False)
            .annotate(lower_number=Lower('number'))
            .filter(lower_number__in={number for number, _ in chunk}, brand_id__in={brand for _, brand in chunk})
            .values_list('lower_number', 'brand_id')
        )
        for key in held & set(chunk):
            del winners[key]
    stats.taken = candidates - len(winners)

    by_brand: dict[int, list[int]] = defaultdict(list)
    for (_, brand_id), pk in winners.items():
        by_brand[brand_id].append(pk)
    names = dict(Brand.objects.filter(pk__in=list(by_brand)).values_list('pk', 'name'))
    for brand_id, pks in by_brand.items():
        vector = RawSQL(
            "COALESCE(search_vector, ''::tsvector) || setweight(to_tsvector('russian'::regconfig, %s), 'B')",
            [names[brand_id]], output_field=SearchVectorField(),
        )
        for chunk in _chunks(pks):
            # brand IS NULL ещё раз: бренд могли поставить с тех пор, как его
            # прочитали (синхронизация с PIM идёт в своей очереди).
            stats.adopted += (Product.objects.filter(pk__in=chunk, brand__isnull=True)
                              .update(brand_id=brand_id, search_vector=vector))
            inherit_product_brands(SupplierProduct.objects.filter(main_product__product_id__in=chunk), index)
    logger.info('brands: бренд поставщика у товаров без бренда — поставлен %s, спор %s, пара занята %s',
                stats.adopted, stats.disputed, stats.taken)
    return stats


def resolve_unmapped() -> ResolutionStats:
    """Пересопоставить строки ПП, у которых бренда нет, — после нового синонима или бренда."""
    return apply_brand_resolution(SupplierProduct.objects.filter(brand__isnull=True, brand_name__isnull=False))


def resolve_all() -> ResolutionStats:
    """Пересопоставить все строки ПП — после правки или удаления синонима, после синхронизации."""
    return apply_brand_resolution(SupplierProduct.objects.all())


def fetch_pim_brands() -> list[dict]:
    """Весь список брендов PIM. Обрезанный список — ошибка, а не «бренды пропали».

    Сортировка по id: по полю со многими равными значениями (createdAt) PIM
    при постраничном чтении молча дублирует и теряет строки.
    """
    query = EntityList(name='Brand', select=BRAND_SELECT, ordering=Ordering(sortBy='id', asc=Asc.ASC))
    result = fetch_list(pim_client.site, query)
    if result.truncated:
        raise RuntimeError(
            f'brands: PIM отдал {len(result.items)} из {result.total} брендов — список неполный, '
            'синхронизация остановлена')
    return result.items


def _brand_fields(row: dict) -> dict:
    return {
        'name': row.get('name') or row['id'],
        'code': row.get('code') or None,
        'is_active': row.get('isActive') is not False,
    }


def sync_brands_from_pim() -> int:
    """Зеркало всего списка брендов PIM; возвращает, сколько брендов изменилось.

    _ensure_pim_brand (pim_sync) заводит бренд, только когда его приносит
    товар; окну «Бренды» нужны и бренды без наших товаров — им и сопоставляют
    написания поставщиков. Бренд, которого нет в полном списке, выключается, не
    удаляется (см. Brand.is_active). Затем все строки ПП пересопоставляются:
    новый бренд PIM мог закрыть очередь, а выключенный — открыть её заново.
    """
    rows = fetch_pim_brands()
    existing = {brand.pim_id: brand for brand in Brand.objects.all()}
    seen: set[str] = set()
    to_create, to_update = [], []
    for row in rows:
        pim_id = row.get('id')
        if not pim_id:
            continue
        seen.add(pim_id)
        values = _brand_fields(row)
        brand = existing.get(pim_id)
        if brand is None:
            to_create.append(Brand(pim_id=pim_id, **values))
        elif any(getattr(brand, name) != value for name, value in values.items()):
            for name, value in values.items():
                setattr(brand, name, value)
            to_update.append(brand)
    for pim_id, brand in existing.items():
        if pim_id not in seen and brand.is_active:
            brand.is_active = False
            to_update.append(brand)
    with transaction.atomic():
        Brand.objects.bulk_create(to_create)
        Brand.objects.bulk_update(to_update, ['name', 'code', 'is_active'])
    resolve_all()
    logger.info('sync_brands_from_pim: брендов в PIM %s, новых %s, изменено %s',
                len(seen), len(to_create), len(to_update))
    return len(to_create) + len(to_update)


def _mirror(row: dict) -> Brand:
    brand, _ = Brand.objects.update_or_create(pim_id=row['id'], defaults=_brand_fields(row))
    return brand


def create_pim_brand(name: str) -> tuple[Brand, bool]:
    """Кнопка «Создать в PIM»: бренд с этим названием в PIM — найденный или новый.

    Возвращает (бренд, создан ли он сейчас). Перед созданием список брендов
    PIM читается заново: бренд могли завести в PIM после последней
    синхронизации, и второй такой же — ровно тот дубль, что потом сливают
    руками. После создания бренд ищется ещё раз, а не берётся из ответа:
    upsertAsync может записать строку и вернуть по ней Failed.

    Строки ПП с этим написанием сопоставляются сразу.
    """
    name = ' '.join((name or '').split())
    key = brand_key(name)
    if not key:
        raise PimBrandError('Пустое название бренда')

    def matching():
        return [row for row in fetch_pim_brands() if brand_key(row.get('name')) == key]

    created = False
    try:
        found = matching()
        if not found:
            results = upsert_async(pim_client.site, [{'entity': 'Brand', 'payload': {'name': name, 'isActive': True}}])
            found = matching()
            if not found:
                detail = (results[0].get('message') if results and isinstance(results[0], dict) else None) or 'нет ответа'
                raise PimBrandError(f'PIM не создал бренд «{name}»: {detail}')
            created = True
    except PimBrandError:
        raise
    except Exception as exc:
        # Сеть, таймаут задания, неполный список: человеку — причина в окне,
        # а не молчаливая 500 (HTMX ошибочный ответ не показывает).
        logger.warning('create_pim_brand: PIM не ответил для «%s»', name, exc_info=True)
        raise PimBrandError(
            f'PIM не ответил ({exc.__class__.__name__}). Если бренд успел создаться, он появится '
            'после «Обновить из PIM»; иначе попробуйте позже') from exc
    if len(found) > 1:
        raise PimBrandError(
            f'В PIM несколько брендов «{name}» ({", ".join(row.get("name") or row["id"] for row in found)}) — '
            'слейте их в PIM и обновите список брендов')
    brand = _mirror(found[0])
    resolve_unmapped()
    return brand, created


def add_alias(name: str, brand: Brand | None, user=None) -> BrandAlias:
    """Синоним «написание → бренд» (brand None — игнорировать) и сопоставление строк ПП.

    Существующий синоним того же ключа перезаписывается: человек поправил
    своё же решение. Затем пересопоставляются все строки, а не только
    несведённые: синоним мог увести написание от бренда, к которому оно
    сводилось неявно.
    """
    name = ' '.join((name or '').split())
    key = brand_key(name)
    if not key:
        raise ValueError('Пустое написание бренда')
    alias, _ = BrandAlias.objects.update_or_create(
        name_key=key, defaults={'name': name, 'brand': brand, 'created_by': user})
    resolve_all()
    return alias


def delete_alias(alias: BrandAlias) -> None:
    alias.delete()
    resolve_all()


@transaction.atomic
def merge_brands(loser: Brand, winner: Brand) -> None:
    """Перенести всё с бренда loser на winner и удалить loser.

    Для брендов, слитых в PIM: у слитого бренда остаются товары (до следующей
    синхронизации контента), строки ПП, синонимы и охваты менеджеров цен
    (PriceManagerBrand — PROTECT, из-за них бренд и не удалить). Менеджер цен,
    у которого в охвате оба бренда, сохраняет одну запись. Написание названия
    loser становится синонимом winner, чтобы прайсы с ним сводились дальше.
    """
    from product_price_manager.models import PriceManagerBrand

    if loser.pk == winner.pk:
        raise ValueError('Бренд нельзя слить сам с собой')
    # Товар — пара (артикул, бренд): товар бренда loser, у которого есть
    # двойник с тем же артикулом у winner, после переноса стал бы второй такой
    # парой. Это один товар, и склеивают его руками — слияние ждёт.
    twins = list(
        Product.objects.filter(brand=loser)
        .filter(Exists(Product.objects.filter(brand=winner, number__iexact=OuterRef('number'))))
        .order_by('number').values_list('number', flat=True)[:MERGE_CONFLICT_EXAMPLES + 1]
    )
    if twins:
        shown = ', '.join(f'«{number}»' for number in twins[:MERGE_CONFLICT_EXAMPLES])
        more = ' и другие' if len(twins) > MERGE_CONFLICT_EXAMPLES else ''
        raise BrandMergeConflict(
            f'У брендов «{loser.name}» и «{winner.name}» есть товары с одним артикулом: {shown}{more}. '
            'Перенесите их строки ГП в товар бренда «' + winner.name + '» и удалите пустые товары, '
            'затем слейте бренды.')
    Product.objects.filter(brand=loser).update(brand=winner)
    SupplierProduct.objects.filter(brand=loser).update(brand=winner)
    BrandAlias.objects.filter(brand=loser).update(brand=winner)
    with_winner = PriceManagerBrand.objects.filter(brand=winner).values('price_manager_id')
    PriceManagerBrand.objects.filter(brand=loser, price_manager_id__in=with_winner).delete()
    PriceManagerBrand.objects.filter(brand=loser).update(brand=winner)
    key = brand_key(loser.name)
    if key and key != brand_key(winner.name):
        BrandAlias.objects.get_or_create(name_key=key, defaults={'name': loser.name, 'brand': winner})
    loser.delete()


def suggest(name: str, keys: dict[str, list[Brand]], limit: int = 3) -> list[Brand]:
    """Похожие бренды PIM для несведённого написания — подсказка, не решение."""
    matches = difflib.get_close_matches(brand_key(name), list(keys), n=limit, cutoff=0.6)
    return [brand for key in matches for brand in keys[key]][:limit]


def same_key_brands(name: str) -> list[Brand]:
    """Активные бренды PIM, чьё название сводится к тому же ключу, — дубль в PIM, если их больше одного."""
    key = brand_key(name)
    return [brand for brand in Brand.objects.filter(is_active=True) if brand_key(brand.name) == key]


def suggestion_keys() -> dict[str, list[Brand]]:
    keys: dict[str, list[Brand]] = defaultdict(list)
    for brand in Brand.objects.filter(is_active=True).only('pk', 'name'):
        key = brand_key(brand.name)
        if key:
            keys[key].append(brand)
    return keys


@dataclass
class UnmappedName:
    name: str
    rows: int
    suppliers: list[str]
    ambiguous: bool = False


def unmapped_names(query: str = '') -> list[UnmappedName]:
    """Очередь окна: написания строк ПП без бренда, которые ничем не сводятся.

    Группировка запросом по сырому написанию: «DeWalt» и «DEWALT» — две строки
    очереди, но один синоним закроет обе (ключ у них общий). Проигнорированные
    написания в очередь не попадают. Больше строк — выше: сопоставление
    сверху вниз быстрее всего поднимает покрытие.

    Подсказки (suggest) здесь не считаются: difflib по сотням брендов на
    каждое из тысяч написаний — секунды на каждую отрисовку списка. Их
    показывает окно сопоставления одного написания.
    """
    groups = (SupplierProduct.objects.filter(brand__isnull=True, brand_name__isnull=False)
              .values('brand_name', 'supplier__name').annotate(rows=Count('pk')))
    if query:
        groups = groups.filter(brand_name__icontains=query)
    index = BrandIndex()
    by_name: dict[str, UnmappedName] = {}
    for group in groups:
        name = group['brand_name']
        found, _ = index.lookup(name)
        if found:
            continue
        item = by_name.setdefault(name, UnmappedName(name=name, rows=0, suppliers=[],
                                                     ambiguous=index.is_ambiguous(name)))
        item.rows += group['rows']
        item.suppliers.append(group['supplier__name'])
    for item in by_name.values():
        item.suppliers.sort()
    return sorted(by_name.values(), key=lambda item: (-item.rows, item.name.lower()))


def unmapped_name(name: str) -> UnmappedName:
    """Одно написание очереди — для окна сопоставления; rows 0, если его уже свели."""
    groups = (SupplierProduct.objects.filter(brand__isnull=True, brand_name=name)
              .values('supplier__name').annotate(rows=Count('pk')).order_by('supplier__name'))
    return UnmappedName(name=name, rows=sum(group['rows'] for group in groups),
                        suppliers=[group['supplier__name'] for group in groups],
                        ambiguous=BrandIndex().is_ambiguous(name))


@dataclass
class Coverage:
    sp_total: int
    sp_with_name: int
    sp_mapped: int
    sp_ignored: int
    sp_unmapped: int
    unmapped_names: int
    mp_total: int
    mp_with_brand: int
    settings_without_brand: list

    @staticmethod
    def percent(part: int, whole: int) -> int:
        return round(100 * part / whole) if whole else 0

    @property
    def sp_with_name_pct(self) -> int:
        return self.percent(self.sp_with_name, self.sp_total)

    @property
    def sp_mapped_pct(self) -> int:
        return self.percent(self.sp_mapped, self.sp_with_name)

    @property
    def mp_with_brand_pct(self) -> int:
        return self.percent(self.mp_with_brand, self.mp_total)


def coverage() -> Coverage:
    """Насколько заполнены бренды — по этим числам решают, когда переходить к ключу (бренд, артикул).

    Строки ГП считаются только поставщиков (строки наборов — без поставщика,
    их бренд — бренд набора). Бренд у строки ГП есть, если сопоставлен бренд её
    строки ПП или у её товара есть бренд PIM.
    """
    sps = SupplierProduct.objects.all()
    sp_total = sps.count()
    named = sps.filter(brand_name__isnull=False)
    sp_with_name = named.count()
    # Сведённые — заявки. У строки с написанием «бренда нет» бренд тоже бывает,
    # но унаследованный от товара (inherit_product_brands): она — «игнор».
    index = BrandIndex()
    no_brand = [name for name in named.values_list('brand_name', flat=True).distinct()
                if index.lookup(name) == (True, None)]
    sp_mapped = named.exclude(brand_name__in=no_brand).filter(brand__isnull=False).count()
    queue = unmapped_names()
    unmapped = sum(item.rows for item in queue)
    mps = MainProduct.objects.filter(supplier__isnull=False)
    mapped_sp = SupplierProduct.objects.filter(main_product=OuterRef('pk'), brand__isnull=False)
    mp_with_brand = mps.filter(Q(Exists(mapped_sp)) | Q(product__brand__isnull=False)).count()
    # «> ''» вместо «не NULL и не ''»: отрицание по многозначной связи Django
    # превращает в подзапрос «ни одной ссылки с ''» по всем Link настройки,
    # а не условие на ту же строку, что key='brand_name'.
    with_brand_column = Q(links__key='brand_name') & (Q(links__value__gt='') | Q(links__initial__gt=''))
    settings_without_brand = list(
        Setting.objects.exclude(pk__in=Setting.objects.filter(with_brand_column).values('pk'))
        .select_related('supplier').order_by('supplier__name', 'name'))
    return Coverage(
        sp_total=sp_total, sp_with_name=sp_with_name, sp_mapped=sp_mapped,
        sp_ignored=sp_with_name - sp_mapped - unmapped, sp_unmapped=unmapped, unmapped_names=len(queue),
        mp_total=mps.count(), mp_with_brand=mp_with_brand,
        settings_without_brand=settings_without_brand,
    )
