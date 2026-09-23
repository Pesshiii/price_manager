"""Экспорт товарной страницы в xlsx: та же выборка, тот же порядок, выбранные колонки.

Строка файла — товар (Product), как и строка страницы. Колонки строк
поставщиков раскладываются по поставщикам: «Цена ИМ • Поставщик А»,
«Цена ИМ • Поставщик Б», … Для цен и остатка перед ними стоит ещё и основное
значение — по приоритету поставщика (Supplier.price_priority /
stock_priority), см. main_value.

Поставщики в колонках — все, у кого есть строка хотя бы у одного
выгружаемого товара, а не все поставщики базы: иначе фильтр по одному
поставщику давал бы файл из пустых колонок остальных.
"""
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

from django.core.files.base import ContentFile
from django.db.models import Prefetch
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font

from main_product_manager.models import MP_PRICES, MainProduct
from supplier_manager.models import Supplier

from .columns import COLUMN_LABELS, SUPPLIER_ROW_COLUMNS
from .filters import CATEGORY_LABEL_DEPTH, ProductFilter, search_terms
from .models import Category, Product, ProductExport
from .tables import ProductTable, SupplierRowTable, best_match_groups_first, category_path

# Параметр сортировки таблицы — тот же, что читает ProductPage.groups_by_category.
SORT_PARAM = ProductTable._meta.prefix + ProductTable._meta.order_by_field

# Цены SupplierProduct — аннотации views._latest_supplier_prices, не поля MainProduct.
SUPPLIER_PRODUCT_PRICES = ['supplier_product_price', 'supplier_product_rrp',
                           'supplier_product_discount_price']
PRICE_COLUMNS = set(MP_PRICES) | set(SUPPLIER_PRODUCT_PRICES)

# Колонки, у которых есть основное значение. Остальные колонки строк
# поставщиков выгружаются только по поставщикам.
STOCK_COLUMN = 'stock'

# Колонки товара, которые в файл не идут: «Действия» — кнопки, фото — картинка.
NOT_EXPORTED = {'actions', 'photo'}

NO_SUPPLIER = 'Без поставщика'

CHUNK_SIZE = 1000


def ordered_product_pks(params) -> list[int]:
    """pk товаров в том порядке, в каком их показывает ProductPage.

    Повторяет цепочку страницы: фильтр → выдача по категориям или сортировка
    по колонке → при поиске в выдаче по категориям — best_match_groups_first
    → order_by таблицы. Разойдись они, файл лёг бы не в том порядке, что
    экран; это держит тест test_export.ExportOrderTests.

    Невалидный фильтр — пустая выборка, как у FilterView со strict.
    """
    from .views import _base_queryset

    sort = params.get(SORT_PARAM)
    by_category = not sort
    filterset = ProductFilter(params, queryset=_base_queryset(by_category=by_category))
    if not filterset.is_valid():
        return []
    queryset = filterset.qs
    if by_category and search_terms(params.get('search')):
        queryset = best_match_groups_first(queryset)
    table = ProductTable(queryset, order_by=sort or None)
    return list(table.data.data.values_list('pk', flat=True))


def export_columns(selected) -> tuple[list[str], list[str]]:
    """Выбранные колонки, разделённые на колонки товара и строк поставщиков."""
    product_columns = [key for key in selected
                       if key not in SUPPLIER_ROW_COLUMNS and key not in NOT_EXPORTED]
    supplier_columns = [key for key in selected
                        if key in SUPPLIER_ROW_COLUMNS and key not in NOT_EXPORTED]
    return product_columns, supplier_columns


def is_zero(value) -> bool:
    return value is None or value == 0


def main_value(values):
    """Основное значение: первое ненулевое по приоритету.

    Ноль и пусто пропускаются — у самого приоритетного поставщика ноль чаще
    значит «цены нет», чем «бесплатно». Если ненулевого нет ни у кого: 0, если
    хоть у кого-то 0 (остаток синхронизировался, товара нет), иначе пусто
    (ни у кого нет данных) — NULL и 0 в остатке разные вещи.
    """
    values = list(values)
    for value in values:
        if not is_zero(value):
            return value
    if any(value is not None for value in values):
        return 0
    return None


def ranked_suppliers(supplier_ids, priority_field) -> list:
    """Поставщики по приоритету: меньше — выше, непроранжированные в конце.

    None в supplier_ids — строки без поставщика; они всегда последние.
    """
    suppliers = list(Supplier.objects.filter(pk__in=[pk for pk in supplier_ids if pk]))
    suppliers.sort(key=lambda s: (getattr(s, priority_field) is None,
                                  getattr(s, priority_field) or 0, s.name, s.pk))
    result = [(supplier.pk, supplier.name) for supplier in suppliers]
    if None in supplier_ids:
        result.append((None, NO_SUPPLIER))
    return result


def _chunks(items, size=CHUNK_SIZE):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _excel_value(value):
    """Значение, которое openpyxl примет.

    datetime с таймзоной он не пишет — переводим в местное время. Объекты
    моделей (колонка «Поставщик» — это Supplier) — строкой, как на экране.
    """
    if isinstance(value, datetime):
        return timezone.localtime(value).replace(tzinfo=None) if value.tzinfo else value
    if value is None or isinstance(value, (str, int, float, Decimal, date)):
        return value
    return str(value)


def _joined(values):
    """Несколько строк одного поставщика: различающиеся значения через «; »."""
    distinct = []
    for value in values:
        if value in (None, '') or value in distinct:
            continue
        distinct.append(value)
    if not distinct:
        return None
    if len(distinct) == 1:
        return distinct[0]
    return '; '.join(str(value) for value in distinct)


class ProductExporter:
    """Собирает xlsx по параметрам страницы и выбранным колонкам."""

    def __init__(self, params, selected_columns):
        self.params = params
        self.product_columns, self.supplier_columns = export_columns(selected_columns)
        # Та же отрисовка «Статуса наличия» и «Срока поставки», что на экране.
        self.row_table = SupplierRowTable([])

    def main_products(self, pks):
        queryset = (MainProduct.objects.filter(product_id__in=pks)
                    .select_related('supplier', 'supplier__currency').order_by('pk'))
        if set(self.supplier_columns) & set(SUPPLIER_PRODUCT_PRICES):
            from .views import _latest_supplier_prices
            queryset = queryset.annotate(**_latest_supplier_prices())
        return queryset

    def products(self, pks):
        categories = Category.objects.select_related(CATEGORY_LABEL_DEPTH)
        queryset = (Product.objects.filter(pk__in=pks).select_related('brand')
                    .prefetch_related(Prefetch('categories', queryset=categories))
                    .defer('search_vector'))
        return {product.pk: product for product in queryset}

    def cell(self, main_product, key):
        if key == 'stock_msg':
            return self.row_table.render_stock_msg(main_product)
        if key == 'delivery_days':
            return self.row_table.render_delivery_days(main_product)
        value = main_product
        for part in key.split('__'):
            value = getattr(value, part, None)
            if value is None:
                return None
        return value

    def header(self, price_suppliers, stock_suppliers):
        titles = ['Артикул', 'Название', 'Бренд', 'Категории']
        titles += [COLUMN_LABELS[key] for key in self.product_columns]
        for key in self.supplier_columns:
            suppliers = stock_suppliers if key == STOCK_COLUMN else price_suppliers
            if key in PRICE_COLUMNS or key == STOCK_COLUMN:
                titles.append(f'{COLUMN_LABELS[key]} (основная)' if key in PRICE_COLUMNS
                              else f'{COLUMN_LABELS[key]} (основной)')
            titles += [f'{COLUMN_LABELS[key]} • {name}' for _, name in suppliers]
        return titles

    def product_cells(self, product, main_products):
        number = product.number or min(
            (mp.sku for mp in main_products if mp.sku), default=None)
        name = product.name or next((mp.name for mp in main_products if mp.name), '')
        categories = sorted(product.categories.all(), key=lambda c: (c.tree_id, c.lft))
        raw = product.raw_data or {}
        cells = [
            number,
            name,
            product.brand.name if product.brand else None,
            '; '.join(' / '.join(category_path(category)) for category in categories) or None,
        ]
        for key in self.product_columns:
            if key == 'tags':
                cells.append(', '.join(raw.get('tag') or []) or None)
            elif key == 'ean':
                cells.append(raw.get('ean') or None)
            elif key == 'pim_status':
                cells.append(raw.get('status') or None)
        return cells

    def supplier_cells(self, main_products, price_suppliers, stock_suppliers):
        by_supplier = defaultdict(list)
        for main_product in main_products:
            by_supplier[main_product.supplier_id].append(main_product)

        cells = []
        for key in self.supplier_columns:
            suppliers = stock_suppliers if key == STOCK_COLUMN else price_suppliers
            if key in PRICE_COLUMNS or key == STOCK_COLUMN:
                # Уникальности (товар, поставщик) у MainProduct нет, и строк у
                # поставщика бывает несколько — внутри поставщика правило то
                # же, что между поставщиками (main_value), строки в порядке pk.
                per_supplier = [
                    main_value(self.cell(mp, key) for mp in by_supplier.get(pk, []))
                    for pk, _ in suppliers
                ]
                cells.append(main_value(per_supplier))
                cells += per_supplier
            else:
                cells += [_joined(self.cell(mp, key) for mp in by_supplier.get(pk, []))
                          for pk, _ in suppliers]
        return cells

    def build(self) -> tuple[bytes, int]:
        pks = ordered_product_pks(self.params)

        supplier_ids = set()
        if self.supplier_columns:
            for chunk in _chunks(pks):
                supplier_ids.update(
                    MainProduct.objects.filter(product_id__in=chunk)
                    .order_by().values_list('supplier_id', flat=True).distinct())
        price_suppliers = ranked_suppliers(supplier_ids, 'price_priority')
        stock_suppliers = ranked_suppliers(supplier_ids, 'stock_priority')

        workbook = Workbook(write_only=True)
        sheet = workbook.create_sheet('Товары')
        sheet.freeze_panes = 'A2'
        bold = Font(bold=True)
        header = []
        for title in self.header(price_suppliers, stock_suppliers):
            cell = WriteOnlyCell(sheet, value=title)
            cell.font = bold
            header.append(cell)
        sheet.append(header)

        for chunk in _chunks(pks):
            products = self.products(chunk)
            main_products = defaultdict(list)
            for main_product in self.main_products(chunk):
                main_products[main_product.product_id].append(main_product)
            # pk__in порядок не хранит — порядок страницы восстанавливается по chunk.
            for pk in chunk:
                product = products.get(pk)
                if product is None:
                    continue
                rows = main_products.get(pk, [])
                cells = self.product_cells(product, rows)
                cells += self.supplier_cells(rows, price_suppliers, stock_suppliers)
                sheet.append([_excel_value(value) for value in cells])

        buffer = BytesIO()
        workbook.save(buffer)
        return buffer.getvalue(), len(pks)


def build_product_export(params, selected_columns, user_id) -> ProductExport:
    content, rows_count = ProductExporter(params, selected_columns).build()
    export = ProductExport(user_id=user_id, rows_count=rows_count)
    # Имя на диске — ASCII; человеческое имя подставляет представление скачивания.
    export.file.save(f'products-{user_id}-{timezone.now():%Y%m%d-%H%M%S}.xlsx',
                     ContentFile(content), save=True)
    return export
