import django_tables2 as tables
from django.db.models import Count, Max, Min, Q, Sum
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.formats import number_format
from django.utils.html import format_html

from main_product_manager.models import MainProduct

from .columns import COLUMN_LABELS, DEFAULT_COLUMNS, PRODUCT_ROW_COLUMNS, SUPPLIER_ROW_COLUMNS
from .models import Product

# Ровно эта строка, когда остаток не синхронизировался ни разу: NULL в stock —
# третье состояние, а не ноль. Та же константа и та же причина, что в
# main_product_manager/grouping.py.
NO_STOCK_DATA = 'Нет данных'


def annotate_product_rows(queryset):
    """Агрегаты по связанным MainProduct для строки товара.

    Настоящая агрегация по Product.main_products, а не оконные функции.
    grouping.py в main_product_manager считает то же самое окнами только потому,
    что там корень выборки — плоский MainProduct и группы приходится
    изображать. Здесь группа это строка, поэтому окна не нужны — и переносить
    их сюда не надо.

    distinct=True у Count обязателен: параллельно висит join на categories из
    фильтра, и без него поставщики посчитались бы с кратностью категорий.
    """
    return queryset.annotate(
        supplier_count=Count('main_products__supplier', distinct=True),
        total_stock=Sum('main_products__stock'),
        min_prime_cost=Min('main_products__prime_cost'),
        max_prime_cost=Max('main_products__prime_cost'),
        in_stock_count=Count('main_products', filter=Q(main_products__stock__gt=0), distinct=True),
    )


class ProductTable(tables.Table):
    """Товарная таблица: строка — Product, поставщики раскрываются под ней."""

    expand = tables.Column(verbose_name='', empty_values=(), orderable=False)
    display_name = tables.Column(verbose_name='Название', accessor='display_name', orderable=False)
    number = tables.Column(verbose_name='Артикул')
    brand = tables.Column(verbose_name='Бренд', default='—')
    product_categories = tables.Column(
        verbose_name='Категории', accessor='pk', orderable=False, empty_values=(),
    )
    supplier_count = tables.Column(verbose_name='Поставщиков', default='—')
    prime_cost_range = tables.Column(
        verbose_name='Себестоимость', accessor='pk', orderable=False, empty_values=(),
    )
    total_stock = tables.Column(verbose_name='Остаток', default=NO_STOCK_DATA)

    # Необязательные колонки — включаются в выборе колонок (product/columns.py).
    photo = tables.Column(verbose_name=COLUMN_LABELS['photo'], empty_values=(), orderable=False)
    tags = tables.Column(verbose_name=COLUMN_LABELS['tags'], empty_values=(), orderable=False)
    ean = tables.Column(verbose_name=COLUMN_LABELS['ean'], empty_values=(), orderable=False)
    pim_status = tables.Column(verbose_name=COLUMN_LABELS['pim_status'], empty_values=(),
                               orderable=False)

    class Meta:
        model = Product
        fields = ()
        sequence = (
            'expand', 'photo', 'display_name', 'number', 'brand', 'product_categories',
            'supplier_count', 'prime_cost_range', 'total_stock', 'tags', 'ean', 'pim_status',
        )
        attrs = {'class': 'table table-hover align-middle'}
        row_attrs = {'data-product-pk': lambda record: record.pk}

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        selected = kwargs.pop('selected_columns', None) or DEFAULT_COLUMNS
        super().__init__(*args, **kwargs)
        for key in PRODUCT_ROW_COLUMNS:
            if key not in selected:
                self.columns.hide(key)

    def render_expand(self, record):
        """Кнопка раскрытия.

        Адрес лежит в data-атрибуте, а не в hx-get, и запрос делает скрипт
        через htmx.ajax(). С hx-get на кнопке HTMX ходил бы на КАЖДЫЙ клик,
        включая сворачивающий: строка честно пряталась, но следом приходил
        ответ и наполнял её заново — лишний запрос на каждое сворачивание и
        контент, живущий в скрытой строке. Видно это только в браузере: в
        тестах обе половины по отдельности проходят.
        """
        return format_html(
            '<button type="button" class="btn btn-sm btn-outline-secondary product-expand"'
            ' data-suppliers-url="{}" data-suppliers-target="#product-suppliers-{}"'
            ' aria-expanded="false"'
            ' aria-label="Показать поставщиков" title="Показать поставщиков">'
            '<i class="bi bi-chevron-down"></i></button>',
            reverse('product-suppliers', kwargs={'pk': record.pk}),
            record.pk,
        )

    def render_product_categories(self, record):
        names = [c.name for c in record.categories.all()]
        return ', '.join(names) if names else '—'

    def render_prime_cost_range(self, record):
        """Диапазон себестоимости по поставщикам товара.

        number_format, а не f'{:.2f}': интерфейс русский, и Django форматирует
        десятичные с запятой. Питоновское форматирование дало бы «99.00» рядом
        с «99,00» в соседней таблице поставщиков.
        """
        low = getattr(record, 'min_prime_cost', None)
        high = getattr(record, 'max_prime_cost', None)
        if low is None and high is None:
            return '—'
        if low == high:
            return number_format(low, decimal_pos=2)
        return f'{number_format(low, decimal_pos=2)} — {number_format(high, decimal_pos=2)}'

    def render_total_stock(self, record):
        """NULL и 0 — разные вещи.

        NULL означает «остаток ни разу не синхронизировался», 0 — «синхронизи-
        ровался и его нет». Sum() по пустому множеству тоже даёт NULL.
        """
        total = getattr(record, 'total_stock', None)
        if total is None:
            return NO_STOCK_DATA
        return total

    # --- необязательные колонки из данных PIM -------------------------------

    def render_photo(self, record):
        """Фото товара — ЕДИНСТВЕННЫЙ сетевой вызов на странице.

        Всё остальное здесь локально (R1 закрыт ровно на этом), но ссылку на
        файл raw_data не хранит — только его id, и адрес приходится спрашивать
        у PIM. get_file_url кэширует ответ на сутки, так что платит только
        первый показ. Поэтому колонка и выключена по умолчанию: включивший её
        соглашается на до 25 запросов к PIM на холодной странице.
        """
        from main_product_manager.utils import get_file_url

        data = record.raw_data or {}
        url = get_file_url(data.get('mainImageId') or data.get('imageId'))
        if not url:
            return '—'
        return format_html(
            '<img src="{}" alt="" style="max-height:50px;max-width:80px;object-fit:contain"'
            ' loading="lazy">',
            url,
        )

    def render_tags(self, record):
        return ', '.join((record.raw_data or {}).get('tag') or []) or '—'

    def render_ean(self, record):
        return (record.raw_data or {}).get('ean') or '—'

    def render_pim_status(self, record):
        return (record.raw_data or {}).get('status') or '—'


class SupplierRowTable(tables.Table):
    """Строки поставщиков под товаром — то, чем была вся таблица старой главной.

    Колонки выбирает пользователь (product/columns.py). Объявлены здесь только
    те, что требуют своей отрисовки; остальные — простые поля MainProduct и
    его поставщика — собираются в __init__ из каталога.
    """

    actions = tables.Column(verbose_name='', empty_values=(), orderable=False)
    name = tables.Column(verbose_name=COLUMN_LABELS['name'])
    stock = tables.Column(verbose_name=COLUMN_LABELS['stock'], empty_values=())
    stock_msg = tables.Column(verbose_name=COLUMN_LABELS['stock_msg'], empty_values=())
    delivery_days = tables.Column(verbose_name=COLUMN_LABELS['delivery_days'], empty_values=())

    DECLARED = ('actions', 'name', 'stock', 'stock_msg', 'delivery_days')

    class Meta:
        model = MainProduct
        fields = ()
        orderable = False
        template_name = 'django_tables2/bootstrap5.html'
        attrs = {'class': 'table table-sm align-middle mb-0'}

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        selected = [key for key in (kwargs.pop('selected_columns', None) or DEFAULT_COLUMNS)
                    if key in SUPPLIER_ROW_COLUMNS]
        # Выбраны только колонки строки товара — таблица поставщиков не должна
        # остаться вовсе без колонок.
        if not selected:
            selected = [key for key in DEFAULT_COLUMNS if key in SUPPLIER_ROW_COLUMNS]
        extra_columns = [
            (key, tables.Column(accessor=key, verbose_name=COLUMN_LABELS[key], default='—'))
            for key in selected if key not in self.DECLARED
        ]
        kwargs['exclude'] = [key for key in self.DECLARED if key not in selected]
        kwargs['sequence'] = selected
        super().__init__(*args, extra_columns=extra_columns, **kwargs)

    def render_actions(self, record):
        return render_to_string('product/partials/supplier_row_actions.html',
                                {'record': record}, request=self.request)

    def render_name(self, record):
        return format_html('<a href="{}">{}</a>',
                           reverse('mainproduct-info', kwargs={'pk': record.pk}), record.name)

    def render_stock(self, record):
        """NULL — «ни разу не синхронизировался», 0 — «синхронизировался, нет»."""
        return NO_STOCK_DATA if record.stock is None else record.stock

    def render_stock_msg(self, record):
        # Остаток проверяется ПЕРЕД поставщиком: «Нет данных» — утверждение про
        # остаток, и строка без поставщика с NULL в остатке про него тоже ничего
        # не знает. Так же было на старой главной.
        if record.stock is None:
            return NO_STOCK_DATA
        if not record.supplier:
            return ''
        if record.stock == 0:
            return record.supplier.msg_navailable or ''
        return record.supplier.msg_available or ''

    def render_delivery_days(self, record):
        # Срок физически берётся из полей поставщика — без него его неоткуда
        # взять, отсюда и расхождение с render_stock_msg.
        if not record.supplier:
            return ''
        days = record.supplier.get_delivery_days_for_stock(record.stock)
        return '' if days is None else days
