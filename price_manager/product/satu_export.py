"""Выгрузка каталога в формате Satu.kz — кнопка в админке товаров.

Файл повторяет выгрузку товаров Satu («export-products-*.xlsx»): два листа,
«Export Products Sheet» и «Export Groups Sheet», те же колонки в том же
порядке, характеристики — повторяющимися тройками
Название_/Измерение_/Значение_Характеристики.

Заполняется только то, что у нас есть (решение владельца, 2026-09-30):

- Код_товара — артикул (Product.number), Название_позиции, Описание
  (longDescription из PIM, иначе description — HTML как есть),
  Поисковые_запросы — теги PIM, Производитель — бренд;
- Наличие — «+» при основном остатке > 0, иначе минимальный срок поставки
  по поставщикам товара, а если его нет — «-»; Количество — основной остаток;
- Страна_производитель, GTIN (ean), MPN и характеристики — из PIM: в зеркале
  (raw_data) их нет, они берутся списком по 100 товаров во время выгрузки.
  Страна и GTIN при пустом поле товара — из атрибутов «Страна производства»
  и «GTIN»/«Штрихкод» (COUNTRY_ATTRIBUTES, GTIN_ATTRIBUTES);
- цены ГП — все семь, отдельными колонками после характеристик, основные
  значения по уровням поставщиков, как в полном csv. Колонки Satu «Цена» и
  «Оптовая_цена» пустые.

Остальное (группы Satu, подразделы, скидки, ссылки на сайт, фото — фото PIM
без токена не открываются) остаётся пустым. Лист групп — только заголовок.

Весь каталог — ~158 тыс. товаров и ~1 600 запросов к PIM. Ширина листа
зависит от товара с наибольшим числом характеристик, а write_only-книга пишет
заголовок первым, поэтому строки сначала пишутся во временный jsonl, и лишь
потом — в xlsx.
"""
from __future__ import annotations

import json
import logging
import tempfile
import time
from decimal import Decimal

from django.core.files import File
from django.http import QueryDict
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

from main_product_manager.models import MP_PRICES, MainProduct
from pim_api import EntityList, FlatEntityList, Where, fetch_list

from . import pim_client
from .columns import COLUMN_LABELS
from .export import STOCK_COLUMN, ProductExporter, _chunks, _excel_value, ordered_product_pks
from .models import ProductExport

logger = logging.getLogger(__name__)

PRODUCTS_SHEET = 'Export Products Sheet'
GROUPS_SHEET = 'Export Groups Sheet'

# Колонки Satu до характеристик — дословно, в порядке их выгрузки.
BASE_TITLES = [
    'Код_товара', 'Название_позиции', 'Поисковые_запросы', 'Описание', 'Тип_товара',
    'Цена', 'Валюта', 'Единица_измерения', 'Минимальный_объем_заказа', 'Оптовая_цена',
    'Минимальный_заказ_опт', 'Ссылка_изображения', 'Наличие', 'Количество', 'Номер_группы',
    'Название_группы', 'Адрес_подраздела', 'Возможность_поставки', 'Срок_поставки',
    'Способ_упаковки', 'Уникальный_идентификатор', 'Идентификатор_товара',
    'Идентификатор_подраздела', 'Идентификатор_группы', 'Производитель',
    'Страна_производитель', 'Скидка', 'ID_группы_разновидностей', 'Личные_заметки',
    'Продукт_на_сайте', 'Cрок действия скидки от', 'Cрок действия скидки до', 'Цена_от',
    'Ярлык', 'HTML_заголовок', 'HTML_описание', 'Код_маркировки_(GTIN)',
    'Номер_устройства_(MPN)', 'Где_находится_товар',
    'Национальный_уникальный_идентификатор_товара_(NTIN)',
]
CHARACTERISTIC_TITLES = ['Название_Характеристики', 'Измерение_Характеристики',
                         'Значение_Характеристики']
# Столько троек в выгрузке Satu; у товара с большим числом лист шире.
MIN_CHARACTERISTICS = 50
GROUP_TITLES = [
    'Номер_группы', 'Название_группы', 'Идентификатор_группы', 'Номер_родителя',
    'Идентификатор_родителя', 'HTML_заголовок_группы', 'HTML_описание_группы',
    'Описание_группы_до_списка_товарных_позиций',
    'Описание_группы_после_списка_товарных_позиций', 'Ссылка_изображения_группы',
]

SATU_COLUMNS = MP_PRICES + [STOCK_COLUMN]
PRICE_TITLES = [COLUMN_LABELS[key] for key in MP_PRICES]

IN_STOCK = '+'
NOT_AVAILABLE = '-'

# Больше — 414 URI Too Long: отбор id in [...] идёт в строке запроса.
PIM_BATCH = 100
PIM_TIMEOUT = 60
# Как у pim_sync: шесть попыток с удвоением — около минуты ожидания. После
# них выгрузка падает, а не пишет товары молча без характеристик.
PIM_RETRIES = 6
# Не countryOfOriginName: с полем-ссылкой *Name в select PIM отдаёт запись без
# id и без значений атрибутов — молча (проверено 2026-09-30). Id страны
# безопасен, название берётся из справочника Country (fetch_countries).
PIM_SELECT = ['id', 'countryOfOriginId', 'ean', 'mpn']

# Типы атрибутов, которые являются характеристиками. link — единица
# измерения атрибута, linkMultiple — связи (состав набора).
CHARACTERISTIC_TYPES = {'varchar', 'text', 'int', 'float', 'bool', 'url'}

# Поля товара PIM countryOfOrigin и ean почти пусты (страна — ни у одного из
# ~283 тыс., ean — у ~10 тыс.; 2026-09-30), а те же данные лежат в атрибутах.
# Колонка Satu берёт первое непустое: поле товара, затем атрибуты по порядку.
# В тройках характеристик значения остаются. «Страна бренда» — не страна
# производства, её здесь нет.
COUNTRY_ATTRIBUTES = ['Страна производства']
GTIN_ATTRIBUTES = ['GTIN', 'Штрихкод']


def _pim_get(query):
    for attempt in range(PIM_RETRIES):
        try:
            return pim_client.site.get(query, timeout=PIM_TIMEOUT)
        except Exception:
            if attempt == PIM_RETRIES - 1:
                raise
            logger.warning('satu_export: PIM не ответил, попытка %s', attempt + 1, exc_info=True)
            time.sleep(2 ** attempt)


def fetch_attributes() -> dict:
    """Справочник атрибутов PIM: {id: (название, ключ сортировки)}."""
    result = fetch_list(pim_client.site, EntityList(
        name='Attribute', select=['id', 'name', 'sortOrder', 'attributeGroupSortOrder']),
        timeout=PIM_TIMEOUT)
    return {
        item['id']: (item.get('name') or '',
                     (item.get('attributeGroupSortOrder') or 0, item.get('sortOrder') or 0))
        for item in result.items
    }


def fetch_countries() -> dict:
    """Справочник стран PIM: {id: название}."""
    result = fetch_list(pim_client.site, EntityList(name='Country', select=['id', 'name']),
                        timeout=PIM_TIMEOUT)
    return {item['id']: item.get('name') or '' for item in result.items}


def fetch_flat_products(pim_ids) -> dict:
    """{id товара PIM: запись с характеристиками} — пачками по PIM_BATCH."""
    result = {}
    for batch in _chunks(list(pim_ids), PIM_BATCH):
        response = _pim_get(FlatEntityList(
            name='Product', select=PIM_SELECT, maxSize=PIM_BATCH,
            where=[Where(attribute='id', type='in', value=batch)]))
        for item in response.get('list') or []:
            result[item['id']] = item
    return result


def _format_value(value, kind):
    if kind == 'bool':
        return 'Да' if value else 'Нет'
    if isinstance(value, float):
        return f'{value:.4f}'.rstrip('0').rstrip('.').replace('.', ',')
    return str(value).strip()


def characteristics(data: dict, attributes: dict) -> list[list[str]]:
    """[[название, единица, значение], ...] в порядке атрибутов PIM, пустые пропущены."""
    items = []
    for code, definition in (data.get('attributesDefs') or {}).items():
        kind = definition.get('type')
        if kind not in CHARACTERISTIC_TYPES:
            continue
        value = data.get(code)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        name, sort = attributes.get(definition.get('attributeId'), (code, (0, 0)))
        unit = (data.get(f'{code}UnitData') or {}).get('symbol') or ''
        items.append((sort, name or code, [name or code, unit, _format_value(value, kind)]))
    items.sort(key=lambda item: (item[0], item[1]))
    return [triple for _, _, triple in items]


def availability(stock, main_products):
    """Наличие Satu: «+», если товар есть, иначе срок поставки в днях — минимальный
    по поставщикам товара, а без него «-»."""
    if stock:
        return IN_STOCK
    days = [mp.supplier.get_delivery_days_for_stock(mp.stock)
            for mp in main_products if mp.supplier_id]
    days = [day for day in days if day is not None]
    return min(days) if days else NOT_AVAILABLE


def _cell(value):
    """Значение ячейки без управляющих символов: на них (\x0b из Word и т. п.)
    openpyxl падает, а с ним — вся выгрузка, уже после всех запросов к PIM."""
    if isinstance(value, str):
        return ILLEGAL_CHARACTERS_RE.sub('', value)
    return _excel_value(value)


def _first(*values):
    return next((value for value in values if value not in (None, '')), None)


def _json_value(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


class SatuExporter(ProductExporter):
    def __init__(self):
        super().__init__(QueryDict(), SATU_COLUMNS)
        self.attributes = {}
        self.countries = {}

    def product_row(self, product, main_products, main_cells, pim_data):
        raw = product.raw_data or {}
        pim = pim_data or {}
        prices = dict(zip(SATU_COLUMNS, main_cells))
        stock = prices[STOCK_COLUMN]
        triples = characteristics(pim, self.attributes) if pim else []
        by_name = {}
        for triple_name, _, value in triples:
            by_name.setdefault(triple_name, value)
        cells = dict.fromkeys(BASE_TITLES)
        number, name = self.product_cells(product, main_products)[:2]
        cells.update({
            'Код_товара': number,
            'Название_позиции': name,
            'Поисковые_запросы': ', '.join(raw.get('tag') or []) or None,
            'Описание': raw.get('longDescription') or raw.get('description') or None,
            'Наличие': availability(stock, main_products),
            'Количество': stock,
            'Производитель': product.brand.name if product.brand else raw.get('brandName'),
            'Страна_производитель': _first(self.countries.get(pim.get('countryOfOriginId')),
                                           *(by_name.get(n) for n in COUNTRY_ATTRIBUTES)),
            'Код_маркировки_(GTIN)': _first(pim.get('ean'),
                                            *(by_name.get(n) for n in GTIN_ATTRIBUTES)),
            'Номер_устройства_(MPN)': pim.get('mpn') or None,
        })
        return {
            'base': [_json_value(cells[title]) for title in BASE_TITLES],
            'characteristics': triples,
            'prices': [_json_value(prices[key]) for key in MP_PRICES],
        }

    def iter_rows(self, pks, price_levels, stock_levels):
        for chunk in _chunks(pks):
            products = self.products(chunk)
            main_products = {}
            for main_product in self.main_products(chunk):
                main_products.setdefault(main_product.product_id, []).append(main_product)
            pim_ids = {(product.raw_data or {}).get('id') for product in products.values()}
            flat = fetch_flat_products(sorted(pim_id for pim_id in pim_ids if pim_id))
            for pk in chunk:
                product = products.get(pk)
                if product is None:
                    continue
                rows = main_products.get(pk, [])
                values = self.supplier_values(rows)
                main_cells = self.main_value_cells(values, self.supplier_costs(rows),
                                                   price_levels, stock_levels)
                yield self.product_row(product, rows, main_cells,
                                       flat.get((product.raw_data or {}).get('id')))

    def write(self, target) -> int:
        """Пишет xlsx в target (бинарный файл); возвращает число товаров."""
        pks = ordered_product_pks(self.params)
        _, price_levels, stock_levels = self.suppliers(pks)
        self.attributes = fetch_attributes()
        self.countries = fetch_countries()

        width = MIN_CHARACTERISTICS
        with tempfile.TemporaryFile('w+', encoding='utf-8') as rows_file:
            for row in self.iter_rows(pks, price_levels, stock_levels):
                width = max(width, len(row['characteristics']))
                rows_file.write(json.dumps(row, ensure_ascii=False) + '\n')
            rows_file.seek(0)

            workbook = Workbook(write_only=True)
            sheet = workbook.create_sheet(PRODUCTS_SHEET)
            sheet.append(BASE_TITLES + CHARACTERISTIC_TITLES * width + PRICE_TITLES)
            for line in rows_file:
                row = json.loads(line)
                triples = [cell for triple in row['characteristics'] for cell in triple]
                triples += [None] * (3 * width - len(triples))
                sheet.append([_cell(value)
                              for value in row['base'] + triples + row['prices']])
            workbook.create_sheet(GROUPS_SHEET).append(GROUP_TITLES)
            workbook.save(target)
        return len(pks)


def build_satu_export(user_id) -> ProductExport:
    with tempfile.TemporaryFile() as raw:
        rows_count = SatuExporter().write(raw)
        raw.seek(0)
        export = ProductExport(user_id=user_id, rows_count=rows_count)
        export.file.save(f'products-satu-{user_id}-{timezone.now():%Y%m%d-%H%M%S}.xlsx',
                         File(raw), save=True)
    return export
